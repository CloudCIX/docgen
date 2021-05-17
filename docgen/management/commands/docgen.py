"""
Docgen that reads our application layout, pulls docstrings and variable names and builds Swagger compatibly JSON to
display documentation that automatically updates with changes to the system
"""

# stdlib
import json
import jsonschema
import logging
import os
import re
import sys
import types
import typing
import yaml
from argparse import ArgumentParser
from copy import deepcopy
from importlib import import_module
from time import perf_counter
# libs
from cloudcix_rest.controllers import ControllerBase
from cloudcix_rest.views import APIView
from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import path
from openapi_spec_validator import openapi_v3_spec_validator
from serpy.serializer import SerializerMeta
# local
from docgen import defaults


DJANGO_PATH_PARAM_PATTERN = re.compile(r'(\<[a-z]+:([a-z_]+)\>)')
DOC_PATH_PARAM_PATTERN = re.compile(r'{([a-z_]+)}')
HTTP_METHOD_NAMES = ('get', 'post', 'put', 'patch', 'delete')
DEFAULT_RESPONSE_DESCRIPTIONS = {
    '200': 'OK',
    '201': 'Created',
    '204': 'No Content',
    '400': 'Input data was invalid',
    '401': 'No or invalid token provided',
    '403': 'No permission for user',
    '404': 'One of the resources specified could not be found',
}
METHOD_NAME_MAP = {
    'put': 'update',
    'patch': 'update',
    'delete': 'delete',
    'post': 'create',
}


class Command(BaseCommand):
    can_import_settings = True
    errors = False
    help = 'Generate documentation for the specified module'

    # Current working references (to avoid loads of params)

    # The current controller class being parsed
    controller_class: typing.Optional[ControllerBase] = None
    # The controller module for the current module
    controller_mod: typing.Optional[types.ModuleType] = None
    # Flag stating whether, if the current method is get, it is list or read
    get_is_list: typing.Optional[bool] = None
    # The name of the current method
    method_name: typing.Optional[str] = None
    # A reference to the part of the spec for the current method
    method_spec: typing.Optional[typing.Dict] = None
    # The name of the Model currently being parsed
    model_name: typing.Optional[str] = None
    # The module being parsed
    module: typing.Optional[types.ModuleType] = None
    # The name of the module being parsed
    module_name: typing.Optional[str] = None
    # The serializer module for the module being parsed
    serializer_mod: typing.Optional[types.ModuleType] = None
    # The spec that will be turned into JSON
    spec: typing.Optional[typing.Dict] = None
    # The tag for the current view being parsed
    tag: typing.Optional[str] = None
    # The URL currently in use
    url: typing.Optional[str] = None
    # The current view file being parsed
    view_file: typing.Optional[types.ModuleType] = None
    # A reference to module.views
    view_module: typing.Optional[types.ModuleType] = None

    def add_arguments(self, parser: ArgumentParser):
        """
        Add extra parameters to the command line running of the method
        """
        parser.add_argument(
            'module_name',
            type=str,
            help='The module to generate documentation for.'
        )
        parser.add_argument(
            '--output',
            '-o',
            help='Overwrite the output location.'
        )
        parser.add_argument(
            '--debug',
            '-d',
            help='Change the log level from INFO to DEBUG',
            action='store_true',
        )

    def handle(self, module_name, *args, **kwargs):
        """
        Parse documentation information for the specified module.

        This command works like a top down parser, starting by parsing the module itself then parsing each of the
        view files and their serializers, then the methods and their controllers and/or permissions.

        The method lastly validates the openapi spec to make sure it's valid before writing out to `settings.DOCS_PATH`
        """
        # Set up logger
        logging.basicConfig(format='%(levelname)-8s: %(message)s')
        self.logger = logging.getLogger('docgen')
        self.logger.setLevel(logging.INFO if not kwargs['debug'] else logging.DEBUG)
        # Set up structure and initial settings
        start = perf_counter()
        self.spec = defaults.DEFAULT_SPEC

        # Attempt to import the module
        self.module_name = module_name
        module = import_module(module_name)

        # Update the `info` field with details from the module
        self.parse_module(module)

        # Load the controller, serializer and views modules here instead of multiple times
        self.controller_mod = import_module(f'{module_name}.controllers')
        self.serializer_mod = import_module(f'{module_name}.serializers')
        self.view_module = import_module(f'{module_name}.views')

        # Iterate through all the view files to build tags
        for attr_name in dir(self.view_module):
            attr = getattr(self.view_module, attr_name)
            if isinstance(attr, types.ModuleType):
                self.view_file = attr
                self.parse_view_file()

        # Iterate through the URL patterns to start building paths
        urlpatterns = import_module(f'{module_name}.urls').urlpatterns
        for urlpattern in urlpatterns:
            self.parse_urlpattern(urlpattern)

        # Check for errors generated while parsing
        if self.errors:
            self.logger.error('ERRORS FOUND WHEN PARSING DOCUMENTATION')
            sys.exit(1)

        # Now validate the generated spec (dump and load to make all keys strings)
        # self.logger.info('OpenAPI Spec Error Checking')
        # errors = openapi_v3_spec_validator.iter_errors(json.loads(json.dumps(self.spec)))

        # valid = True
        # for error in errors:
        #     valid = False
        #     self.logger.error(f'{error.message} @ {error.path}')
        # if not valid:
        #     sys.exit(1)
        # else:
        #     self.logger.info('OK')

        # Write out the generated docs to a JSON file
        output_path = kwargs['output'] or settings.DOCS_PATH
        with open(output_path, 'w') as f:
            json.dump(self.spec, f, sort_keys=True)
        end = perf_counter()

        self.logger.info(f'Documentation generated in {end - start} seconds!')

    # Parser methods

    def parse_module(self, module: types.ModuleType):
        """
        Parse the info from the module for the spec
        """
        self.logger.debug(f'parse_module: Parsing documentation for {self.module_name}')
        info = self.spec['info']
        info['title'] = self.capitalise(self.module_name)
        try:
            version = module.__version__
            if len(version.split('.')) != 3:
                raise ValueError
        except AttributeError:
            self.logger.error(f'parse_module: __version__ for {self.module_name} is either missing or not a string', exc_info=True)
            self.errors = True
            return
        except ValueError:
            self.logger.error(f'parse_module: __version__ for {self.module_name} does not appear to follow SemVer', exc_info=True)
            self.errors = True
            return
        info['version'] = version
        info['description'] = self.ensure_docstring(module).strip()
        # Add the servers field
        self.spec['servers'] = [{'url': f'https://{self.module_name}.api.cloudcix.com/'}]
        # Add the download link for the JSON format
        self.spec['externalDocs'] = {
            'description': 'View Docs in JSON format',
            'url': f'https://{self.module_name}.api.cloudcix.com/documentation/'
        }

    def parse_view_file(self):
        """
        Create a tag entry for the current view file in self.view
        """
        name = self.get_tag_name(self.view_file)
        self.logger.debug(f'parse_view_file: Parsing {name}')
        description = (self.ensure_docstring(self.view_file) or '').strip()
        self.spec['tags'].append({'name': name, 'description': description})

    def parse_urlpattern(self, urlpattern: path):
        """
        Given a URL pattern object, begin creating a new path and parse the view class for details
        """
        view_class_name = urlpattern.lookup_str.split('.')[-1]
        view_file_str = '.'.join(urlpattern.lookup_str.split('.')[:-1])
        self.url = self.get_url(str(urlpattern.pattern))
        self.logger.debug(f'parse_urlpattern: Parsing {self.url}')
        self.spec['paths'][self.url] = {}

        # Get the tag to add to all of the methods in the service
        service_file = import_module(view_file_str)
        self.tag = self.get_tag_name(service_file)

        # Parse the view class
        view_class = getattr(self.view_module, view_class_name)
        self.parse_view_class(view_class)

    def parse_view_class(self, view_class: types.ModuleType):
        """
        Parse all the methods in the given view class and add them to the spec, as well as the serializer
        """
        class_name = view_class.__name__
        self.logger.debug(f'\tparse_view_class: Parsing {class_name}')
        self.get_is_list = 'Collection' in class_name
        self.model_name = class_name.replace('Collection', '').replace('Resource', '')

        # Check for Serializer and parse the output schemas
        # First check if the user has defined a specific serializer class on the view class
        serializer = getattr(view_class, 'serializer_class', None)
        if serializer is None:
            # If they haven't specified one on the class, retrieve the Serializer as per the old pattern
            serializer = getattr(self.serializer_mod, f'{self.model_name}Serializer', None)
        self.parse_serializer(serializer)

        # Iterate through the methods we're looking for and parse them
        for method_name in HTTP_METHOD_NAMES:
            method = getattr(view_class, method_name, None)
            if method is None:
                continue
            self.method_name = method.__name__
            self.parse_view_method(method)

    def parse_view_method(self, method: types.FunctionType):
        """
        Parse the current method
        """
        self.logger.debug(f'\t\tparse_view_method: Parsing {self.method_name}')
        self.spec['paths'][self.url][self.method_name] = {}
        self.method_spec = self.spec['paths'][self.url][self.method_name]
        self.method_spec['tags'] = [self.tag]
        # Check if the method is patch, in which case we can copy the PUT data and make a few changes
        if self.method_name == 'patch':
            self.parse_patch_method()
            return
        # Method docstrings should be done in YAML form so we can update the method spec with that
        try:
            method_doc = yaml.safe_load(self.ensure_docstring(method))
            necessary_keys = {'summary', 'description', 'responses'}
            present_keys = set(method_doc.keys())
            if not necessary_keys <= present_keys:
                missing = f'[{", ". join(necessary_keys - present_keys)}]'
                self.logger.error(
                    f'parse_view_method: Necessary keys missing for {self.model_name}.{self.method_name}: {missing}',
                )
                self.errors = True
                return
            self.method_spec.update(method_doc)
        except yaml.scanner.ScannerError:
            self.logger.error(
                f'parse_view_method: Could not load YAML for {self.model_name}.{self.method_name}',
                exc_info=True,
            )
            self.errors = True
            return
        except ValueError:
            self.logger.error(
                f'parse_view_method: Expected YAML for {self.model_name}.{self.method_name} to be a dict, '
                f'received {type(method_doc)}.',
                exc_info=True,
            )
            self.errors = True
            return
        # Remove the path_params key and parse that with the url
        self.parse_path_params(self.method_spec.pop('path_params', {}))
        # Add data from the method's controller (if exists)
        # First check the method_spec to see if a `controller` key is defined
        controller_name = self.method_spec.pop('controller', None)
        self.parse_controller(controller_name)
        # Add permission details to the method description
        self.parse_permissions()
        # Ensure the responses are in the right schema
        self.install_default_response_data()

    def parse_patch_method(self):
        """
        Do a slight tweak on the handling for PATCH
        """
        url_spec = self.spec['paths'][self.url]
        put_spec = url_spec.get('put', None)
        if put_spec is None:
            self.logger.error(f'parse_patch_method: No PUT data found for {self.url}')
            self.errors = True
            return
        url_spec['patch'] = deepcopy(put_spec)
        # Make some minor changes
        try:
            url_spec['patch']['description'] += (
                '\n\nThe difference between `PUT` and `PATCH` is that you do not have to send all of the '
                'record\'s data in order to update it. Therefore, treat all of the Update schema as optional.'
            )
        except KeyError:
            self.logger.error(f'parse_patch_method: No PUT description found for {self.url}', exc_info=True)
            self.errors = True

    def parse_path_params(self, path_params: typing.Dict[str, typing.Dict[str, str]]):
        """
        Given a URL and the path param definitions from the method docstring, add the path param details to the docs
        """
        self.logger.debug(f'\t\t\tparse_path_params: Parsing path parameters in {self.url}')
        self.method_spec.setdefault('parameters', [])
        # Find all the path parameters
        params = DOC_PATH_PARAM_PATTERN.findall(self.url)
        # For each of them, ensure that they have been defined in the docstring
        for param in params:
            details = path_params.pop(param, None)
            if details is None:
                self.logger.error(
                    f'parse_path_params: Path param {param} in {self.url} was not defined for {self.method_name}',
                )
                self.errors = True
                continue
            # Details will be a dictionary with a small bit of information so we'll make a dict and update it
            param_type = details.pop('type', None)
            if param_type is None:
                self.logger.error(
                    f'parse_path_params: Path param {param} in {self.url} has no type data in {self.method_name}',
                )
                self.errors = True
                continue
            param_data = {
                'in': 'path',
                'required': True,
                'name': param,
                'schema': {
                    'type': param_type,
                },
            }
            param_data.update(details)
            self.method_spec['parameters'].append(param_data)
        if path_params != {}:
            extra_params = ', '.join(path_params.keys())
            self.logger.error(
                f'parse_path_params: Extra path params defined for {self.url} in {self.method_name}: {extra_params}',
            )
            self.errors = True

    def parse_controller(self, explicit_controller_name: str = None):
        """
        Parse the controller for the given method (if one exists)
        :param explicit_controller_name: If the method docstring specifies a controller, this will be the name specified
            else None
        """
        # Methods: list, create, update
        self.logger.debug(
            f'\t\t\tparse_controller: Attempting to parse Controller for {self.model_name}.{self.method_name}',
        )
        # Check if this is a list method and if so, add filter and order details to description, and add params
        if self.method_name == 'get' and self.get_is_list:
            if explicit_controller_name is None:
                self.controller_class = getattr(self.controller_mod, f'{self.model_name}ListController', None)
            else:
                self.controller_class = getattr(self.controller_mod, explicit_controller_name, None)
            if self.controller_class is not None:
                try:
                    self.method_spec['description'] += '\n\n' + self.get_list_details()
                except KeyError:
                    self.logger.error(f'parse_controller: No list description found for {self.url}', exc_info=True)
                    self.errors = True
                    return
            # Also add the default parameters
            self.method_spec.setdefault('parameters', [])
            self.method_spec['parameters'] += defaults.DEFAULT_LIST_PARAMETERS
        # Otherwise, check if it is a create or update request and parse the requestBody details from the controller
        elif self.method_name in ['post', 'put']:
            if explicit_controller_name is None:
                controller_type = 'Create' if self.method_name == 'post' else 'Update'
                self.controller_class = getattr(
                    self.controller_mod,
                    f'{self.model_name}{controller_type}Controller',
                    None,
                )
            else:
                self.controller_class = getattr(self.controller_mod, explicit_controller_name, None)
            if self.controller_class is not None:
                self.parse_input_schema()

    def parse_input_schema(self):
        """
        Parse an input controller to generate the request body for the docs
        """
        self.logger.debug(f'\t\t\t\tparse_input_schema: Generating input schema for {self.model_name}')
        controller_name = self.controller_class.__name__
        schema_name = controller_name.replace('Controller', '')
        # Iterate through the Controller.Meta.validation_order to get field names and add them to the requestBody
        operation = 'create' if 'Create' in schema_name else 'update'
        self.method_spec['requestBody'] = {
            'description': f'Data required to {operation} a record',
            'required': True,
            'content': {
                'application/json': {
                    'schema': {
                        '$ref': f'#/components/schemas/{schema_name}',
                    },
                },
            },
        }
        # Now build the schema
        schema = {
            'type': 'object',
            'required': [],
            'properties': {}
        }
        for field in self.controller_class.Meta.validation_order:
            # Get the method and the doc string from the method and parse the YAML
            validator = getattr(self.controller_class, f'validate_{field}', None)
            if validator is None:
                self.logger.error(f'parse_input_schema: Could not find validate_{field} in {controller_name}')
                self.errors = True
                continue
            try:
                field_data = yaml.safe_load(self.ensure_docstring(validator))
            except yaml.scanner.ScannerError:
                self.logger.error(
                    f'parse_input_schema: Could not load YAML for {controller_name}.validate_{field}',
                    exc_info=True,
                )
                self.errors = True
                continue
            # Skip generative methods
            if field_data.get('generative', False):
                continue
            try:
                if field_data.pop('required', True) and self.method_name != 'patch':
                    schema['required'].append(field)
            except AttributeError:
                self.logger.error(
                    f'parse_input_schema: Expected field data for {controller_name}.validate_{field} to be dict, '
                    f'received {type(field_data)}',
                    exc_info=True,
                )
                self.errors = True
                return
            # Check for required keys
            necessary_keys = {'description', 'type'}
            present_keys = set(field_data.keys())
            if not necessary_keys <= present_keys:
                if '$ref' not in field_data:
                    self.logger.error(
                        f'parse_input_schema: {controller_name}.validate_{field} is missing required fields; '
                        ', '.join(necessary_keys - present_keys),
                    )
                    self.errors = True
                    return
            schema['properties'][field] = field_data
        # If required is empty, remove it
        if schema['required'] == []:
            schema.pop('required')
        # Add the schema to the docs
        self.spec['components']['schemas'][schema_name] = schema

    def parse_permissions(self):
        """
        Parse the permission method's docstring (if exists)
        """
        self.logger.debug(
            f'\t\t\tparse_permissions: Attempting to find and parse {self.module_name}.permissions'
            f'.{self.model_name.lower()}',
        )
        try:
            permission_file = import_module(f'{self.module_name}.permissions.{self.model_name.lower()}')
        except ModuleNotFoundError:
            # No permission checking, which is fine
            return
        if self.method_name == 'get':
            perm_method_name = 'list' if self.get_is_list else 'read'
        else:
            perm_method_name = METHOD_NAME_MAP[self.method_name]
        permission_method = getattr(getattr(permission_file, 'Permissions', None), perm_method_name, None)
        if permission_method is not None:
            self.method_spec['description'] += '\n\n' + self.get_permission_details(permission_method)

    def parse_serializer(self, serializer: SerializerMeta):
        """
        Given a serializer, create the output schemas (<Model>, <Model>Response, <Model>List)
        """
        # If there's no Serializer, that should be fine
        if serializer is None:
            return
        serializer_name = serializer.__name__
        self.logger.debug(f'\t\tparse_serializer: Parsing {serializer_name}')

        # Avoid parsing serializers more than once
        schemas = self.spec['components']['schemas']
        if self.model_name in schemas:
            self.logger.debug(f'\t\tparse_serializer: {serializer_name} already parsed. Skipping.')
            return
        # We also use YAML docstrings in the serializer so lets just load that in
        try:
            serializer_items = yaml.safe_load(self.ensure_docstring(serializer))
        except yaml.scanner.ScannerError:
            self.logger.error(f'parse_serializer: Could not load YAML for {serializer_name}', exc_info=True)
            self.errors = True
            return
        try:
            required = list(serializer_items.keys())  # Output, therefore all keys should be there
        except AttributeError:
            self.logger.error(
                f'parse_serializer: Expected YAML for {serializer_name} to be dict, '
                f'received {type(serializer_items)}',
                exc_info=True
            )
            self.errors = True
            return
        # Ensure that all keys are present in both places and there are no extras in either
        doc_fields = set(serializer_items.keys())
        for field_name in serializer._field_map:
            if 'old_' in field_name:
                # Skip fields used for backwards compatibility
                continue
            if field_name not in doc_fields:
                # Field present in Serializer but not in docstring
                self.logger.error(
                    f'parse_serializer: Field {field_name} defined in {serializer_name} but is missing from the '
                    'Serializer docstring',
                )
                self.errors = True
                continue
            # Remove the key from the keys in the docstring
            doc_fields.remove(field_name)
            # Check that the docstring contains the right keys for this field
            field_items = serializer_items[field_name]
            if '$ref' not in field_items:
                # Check that both description and type are present (other checking is done by spec validator)
                if 'description' not in field_items or 'type' not in field_items:
                    self.logger.error(
                        f'parse_serializer: Field {field_name} in {serializer_name} is missing required keys. Check '
                        'that it has either "$ref" or "description" and "type" defined.',
                    )
                    self.errors = True
                    continue

                # If the type is an array, check if the `items` key exists and check if it contains a $ref
                if field_items['type'] == 'array':
                    if 'items' not in field_items:
                        self.logger.error(
                            f'parse_serializer: Field {field_name} in {serializer_name} has its type set to "array" '
                            'but has no items key specified.',
                        )
                        self.errors = True
                        continue
                    if '$ref' in field_items['items']:
                        self.parse_sub_serializer(serializer_name, field_items['items']['$ref'])
            else:
                # Ensure that the ref exists already and if not, attempt to parse it (except if it's a recursive ref)
                self.parse_sub_serializer(serializer_name, field_items['$ref'])

        # Check that doc_fields is empty
        if len(doc_fields) != 0:
            self.logger.error(
                f'parse_serializer: Fields "{", ".join(doc_fields)} were defined in the docstring for {serializer_name}'
                ' but were not defined in the Serializer itself.',
            )
            self.errors = True
            return
        # Create the model schema
        schemas[self.model_name] = {
            'type': 'object',
            'required': required,
            'properties': serializer_items,
        }

        # Create the ModelResponse schema
        schemas[f'{self.model_name}Response'] = {
            'type': 'object',
            'properties': {
                'content': {
                    '$ref': f'#/components/schemas/{self.model_name}',
                },
            },
        }

        # Create the ModelList schema
        schemas[f'{self.model_name}List'] = {
            'type': 'object',
            'properties': {
                'content': {
                    'type': 'array',
                    'items': {
                        '$ref': f'#/components/schemas/{self.model_name}',
                    },
                },
                '_metadata': {
                    '$ref': '#/components/schemas/ListMetadata',
                },
            },
        }

    def parse_sub_serializer(self, serializer: str, ref: str):
        """
        If a '$ref' is found inside a serializer, this method will be called to ensure that the referenced item is
        also parsed.
        Avoids recursive parses.
        :param serializer: The name of the serializer currently being parsed
        :param ref: The reference to the sub serializer that should be checked
        """
        # Get the sub name out of the ref
        sub_serializer_name = ref.split('/')[-1]
        # Check that it's not the same name as the one being parsed right now
        if serializer == sub_serializer_name:
            return
        self.logger.debug(f'\t\tparse_serializer: Ensuring {sub_serializer_name} is parsed.')
        sub_serializer = getattr(self.serializer_mod, f'{sub_serializer_name}Serializer', None)
        # Temporarily update self.model_name to be the new model being parsed
        parent_model, self.model_name = self.model_name, sub_serializer_name
        self.parse_serializer(sub_serializer)
        self.model_name = parent_model

    # Helper Methods

    def capitalise(self, string: str) -> str:
        """
        Takes in a string, and capitalises every word in it
        """
        return ' '.join([
            s.capitalize()
            for s in string.split()
        ])

    def doc_trim(self, docstring: str) -> str:
        """
        Trim leading indentation from a docstring
        """
        if not docstring:
            return ''
        # Convert tabs to spaces (following the normal Python rules) and split into a list of lines:
        lines = docstring.expandtabs().splitlines()
        # Determine minimum indentation (first line doesn't count):
        indent = float('inf')
        for line in lines:
            stripped = line.lstrip()
            if stripped:
                indent = min(indent, len(line) - len(stripped))
        # Remove indentation (first line is special):
        trimmed = [lines[0].strip()]
        if indent < float('inf'):
            for line in lines:
                trimmed.append(line[indent:].rstrip())
        # Strip off trailing and leading blank lines:
        while trimmed and not trimmed[-1]:
            trimmed.pop()
        while trimmed and not trimmed[0]:
            trimmed.pop(0)
        # Return a single string:
        return '\n'.join(trimmed)

    def ensure_docstring(self, obj: object) -> str:
        """
        Attempt to get the docstring for the supplied object.
        Add an error if no docstring exists
        """
        doc = obj.__doc__
        if obj.__doc__ is None:
            self.logger.error(f'ensure_docstring: {obj.__name__} was expected to have a docstring but it does not')
            self.errors = True
            doc = ''
        return self.doc_trim(doc)

    def get_list_details(self) -> str:
        """
        Given a list controller class, parse docstrings and Metadata to generate search / exclude and ordering details
        """
        all_filters = '\n'.join([
            f'- {field} ({", ".join(modifiers)})' if len(modifiers) > 0 else f'- {field}'
            for field, modifiers in self.controller_class.Meta.search_fields.items()
        ])
        all_orders = '\n'.join([
            f'- {field}' if i > 0 else f'- {field} (default)'
            for i, field in enumerate(self.controller_class.Meta.allowed_ordering)
        ])
        return self.doc_trim(f"""
## Filtering
The following fields and modifiers can be used to filter records from the list;

{all_filters}

To search, simply add `?search[field]=value` to include records that match the request, or `?exclude[field]=value` to
exclude them. To use modifiers, simply add `?search[field__modifier]` and `?exclude[field__modifier]`

## Ordering
The following fields can be used to order the results of the list;

{all_orders}

To reverse the ordering, simply prepend a `-` character to the request. So `?order=field` orders by `field` in ascending
order, while `?order=-field` orders in descending order instead.
"""
)

    def get_permission_details(self, permission_method: types.FunctionType) -> str:
        """
        Given a permission method, parse docstrings and generate verbose permission details
        """
        perm_doc = self.ensure_docstring(permission_method)
        # Check if ' -' exists in the docstring to prevent use of indented lists for docstrings
        if ' -' in perm_doc:
            self.logger.error(
                f'parse_permissions: It appears that the list in the docstring for {self.module_name}.permissions.'
                f'{self.model_name.lower()}.{permission_method.__name__} has been indented. Please have the list '
                'characters in line with the initial line of the docstring to avoid rendering errors in the docs',
            )
            self.errors = True
            return ''
        return self.doc_trim(f"""
## Permissions
{perm_doc}
"""
)

    def get_service_name(self, file_path: str) -> str:
        """
        Given a path to a service file, get the name in verbose english
        """
        return self.capitalise(os.path.basename(file_path).replace('.py', '').replace('_', ' '))

    def get_tag_name(self, service_file: types.ModuleType) -> str:
        """
        Given a view file, get the name of its tag
        """
        return self.get_service_name(service_file.__file__)

    def get_url(self, url_pattern: str) -> str:
        """
        Given a URL pattern, replace Django's path params with OpenAPI path params
        """
        path_params = DJANGO_PATH_PARAM_PATTERN.findall(url_pattern)
        if len(url_pattern) == 0:
            return '/'
        if url_pattern[0] != '/':
            url_pattern = f'/{url_pattern}'
        for pattern, name in path_params:
            url_pattern = url_pattern.replace(pattern, f'{{{name}}}')
        return url_pattern

    def install_default_response_data(self):
        """
        Given a parsed method docstring, ensure the necessary data for the responses exists
        """
        self.logger.debug('\t\t\tinstall_default_response_data')
        responses = self.method_spec.setdefault('responses', {})
        for code, details in responses.items():
            # Check for default data (reuse responses if it is a 4XX response)
            # Reuse only if they don't specify anything
            if str(code)[0] == '4' and len(details) == 0:
                responses[code] = {'$ref': f'#/components/responses/{code}'}
                continue

            # If it is a 2XX code we need to populate the details and content if not already
            if 'description' not in details:
                responses[code]['description'] = DEFAULT_RESPONSE_DESCRIPTIONS.get(str(code), 'none')

            # For content, it's a little more tricky; check response code and method
            if 'content' not in details:
                    default = {
                        'application/json': {
                            'schema': {},
                        },
                    }
                    # Skip code 204 because it doesn't matter

                    # If created, read or updated
                    if str(code) == '201' or (str(code) == '200' and (
                            self.method_name != 'get' or not self.get_is_list)):
                        # Return <Model>Response
                        default['application/json']['schema']['$ref'] = (
                            f'#/components/schemas/{self.model_name}Response'
                        )
                        details['content'] = default
                    elif str(code) == '200' and self.method_name == 'get' and self.get_is_list:
                        default['application/json']['schema']['$ref'] = f'#/components/schemas/{self.model_name}List'
                        details['content'] = default

            # Remove anything that has its value as 'none' (i.e. to have no content)
            for k in list(details.keys()):
                if details[k] == 'none':
                    details.pop(k)

        # Add the 401 response
        responses[401] = {'$ref': '#/components/responses/401'}
