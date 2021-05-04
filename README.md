# docgen

A documentation generator that reads docstrings and variables defined in the `controllers`, `permissions`, `serializers`, `urls`, and `views` of a CloudCIX Application, and uses the details to generate OpenAPI compliant JSON to be used by https://docs.cloudcix.com.

The current version of the [docgen Wiki](wiki/home) is in line with the work done in the Membership Python 3 Application, so look to that if there's any confusion.

## Usage

1. Install the module using `pip`;
    - `pip install git+https://github.com/CloudCIX/docgen.git`
2. Add `docgen` to `INSTALLED_APPS` in the Django settings file
3. Set up Docstrings as per [this guide](#docstrings)
4. Add a `DOCS_PATH` setting to the Django settings file, giving a path to store the generated JSON file
5. Run `python manage.py docgen <application>` to generate documentation for `<application>`

*Example settings.py*
```python
INSTALLED_APPS = [
    ...
    'docgen',
    ...
]
...
DOCS_PATH = '/application_framework/system_conf/docs.json'
```

## Optional Arguments
- `--output`
    - Specify a new output path rather than using `settings.DOCS_PATH`
- `--debug`
    - Turn on some level of debug logging to try and help find out why things aren't working

# docgen Wiki
The [docgen Wiki](wiki/home) details how docstrings and other things should be laid out in a project for correct documentation to be generated.

## Pre-Reading
Most documentation is done through Python [docstrings](https://www.pythonforbeginners.com/basics/python-docstrings)

You should also familiarise yourself with the [OpenAPI Documentation layout](https://swagger.io/docs/specification/about/) first before diving in to do documentation.

Also, since some docstrings are parsed with YAML, it is recommended to look at the [YAML specification](https://cloudslang-docs.readthedocs.io/en/latest/overview/yaml_overview.html) for details.

## Docstrings
In order to get as much information into the docstrings as possible, without making them look ugly, we're going to use a YAML subset for most docstrings.
The docgen tool uses `yaml.load` on the following docstrings;

- [Controller Validation Methods](wiki/validation_methods)
- [Serializers](wiki/serializers)
- [View Methods](wiki/view_methods) (`get`, `post`, `put` and `delete`)

The docgen tool also pulls docstrings from the following locations, albeit not parsing them as YAML;

- [`__init__.py`](wiki/init)
- [View Files](wiki/view_files)
- [Permission Methods](wiki/permission_methods)

The structure of the docstrings are outlined in their respective wiki entries.

## Other Documentation Sources
For list methods, the documentation for fields usable for filtering and ordering are generated from the `ListController.Meta.search_fields` and `ListController.Meta.allowed_ordering` respectively.

For ordering, it also assumes that the first field in the tuple is the default (as it should be) and marks it as such.

## Error Checking
This tool is set up to be super strict when it comes to parsing the information from the code. Each of the above wiki pages will have a section detailing what things will cause errors when the respective section is being parsed.

The tool goes through the entire codebase before printing out all the errors, so all errors in one run of the tool will be presented to the user at once.
