"""
Some default data needed for the generation of docs
"""

DEFAULT_SPEC = {
    'openapi': '3.0.0',
    'info': {
        'contact': {
            'email': 'developers@cloudcix.com',
        },
    },
    'tags': [],
    'security': [
        {'XAuthToken': []},
    ],
    'paths': {},
    'components': {
        'responses': {
            '400': {
                'description': 'Input data was invalid',
                'content': {
                    'application/json': {
                        'schema': {
                            'oneOf': [
                                {'$ref': '#/components/schemas/Error'},
                                {'$ref': '#/components/schemas/MultiError'},
                            ],
                        },
                    },
                },
            },
            '401': {
                'description': 'No / invalid token provided',
                'content': {
                    'application/json': {
                        'schema': {
                            'type': 'object',
                            'properties': {
                                'detail': {
                                    'type': 'string',
                                    'description': 'Verbose error message explaining the error',
                                },
                            },
                        },
                    },
                },
            },
            '403': {
                'description': 'Permission denied for this user',
                'content': {
                    'application/json': {
                        'schema': {
                            '$ref': '#/components/schemas/Error',
                        },
                    },
                },
            },
            '404': {
                'description': 'One of the specified resources could not be found',
                'content': {
                    'application/json': {
                        'schema': {
                            '$ref': '#/components/schemas/Error',
                        },
                    },
                },
            },
        },
        'securitySchemes': {
            'XAuthToken': {
                'type': 'apiKey',
                'in': 'header',
                'name': 'X-Auth-Token',
            },
        },
        'schemas': {
            'ListMetadata': {
                'type': 'object',
                'required': ['total_records', 'page', 'limit', 'order', 'warnings'],
                'properties': {
                    'total_records': {
                        'type': 'integer',
                        'description': 'The total number of records found for the given search',
                    },
                    'page': {
                        'type': 'integer',
                        'description': 'The value of page that was used for the request',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'The value of limit that was used for the request',
                    },
                    'order': {
                        'type': 'string',
                        'description': 'The value of order that was used for the request',
                    },
                    'warnings': {
                        'type': 'array',
                        'items': {
                            'type': 'string',
                        },
                        'description': (
                            'A list of warnings generated during execution. Any invalid search filters used '
                            'will cause a warning to be generated, for example.'
                        ),
                    },
                },
            },
            'Error': {
                'type': 'object',
                'required': ['error_code', 'detail'],
                'properties': {
                    'error_code': {
                        'type': 'string',
                        'description': 'CloudCIX error code for the error',
                    },
                    'detail': {
                        'type': 'string',
                        'description': 'Verbose version of the error message',
                    },
                },
            },
            'MultiError': {
                'description': (
                    'A map of field names to Error objects representing an error that was found with the data '
                    'supplied for that field'
                ),
                'type': 'object',
                'required': ['errors'],
                'properties': {
                    'errors': {
                        'type': 'object',
                        'additionalProperties': {
                            '$ref': '#/components/schemas/Error',
                        },
                    },
                },
            },
        },
    },
}

DEFAULT_LIST_PARAMETERS = [
    {
        'name': 'exclude',
        'in': 'query',
        'description': (
            'Filter the result to objects that do not match the specified filters. '
            'Possible filters are outlined in the individual list method descriptions.'
        ),
        'required': False,
        'schema': {
            'type': 'object',
        },
        'style': 'deepObject',
        'explode': True,
    },
    {
        'name': 'limit',
        'in': 'query',
        'description': 'The limit of the number of objects returned per page',
        'required': False,
        'schema': {
            'type': 'number',
            'minimum': 0,
            'maximum': 100,
            'default': 50,
        },
    },
    {
        'name': 'order',
        'in': 'query',
        'description': (
            'The field to use for ordering. Possible fields and the default are outlined in the '
            'individual method descriptions.'
        ),
        'required': False,
        'schema': {
            'type': 'string',
        },
    },
    {
        'name': 'page',
        'in': 'query',
        'description': 'The page of records to return, assuming `limit` number of records per page.',
        'required': False,
        'schema': {
            'type': 'number',
            'minimum': 0,
            'default': 0,
        },
    },
    {
        'name': 'search',
        'in': 'query',
        'description': (
            'Filter the result to objects that match the specified filters. '
            'Possible filters are outlined in the individual list method descriptions.'
        ),
        'required': False,
        'schema': {
            'type': 'object',
        },
        'style': 'deepObject',
        'explode': True,
    },
]
