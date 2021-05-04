#!/usr/bin/env python

from setuptools import setup

with open('README.md', 'r') as f:
    readme = f.read()

with open('requirements.txt', 'r') as f:
    requires = f.read().split('\n')

setup(
    name='docgen',
    version='1.0.1',
    description='OpenAPI Documentation Generator for CloudCIX Applications',
    long_description=readme,
    author='CloudCIX',
    author_email='developers@cloudcix.com',
    packages=[
        'docgen',
        'docgen.management',
        'docgen.management.commands',
    ],
    keywords=['cix', 'cloudcix', 'openapi', 'documentation'],
    install_requires=requires,
    include_package_data=True,
    license='Apache 2.0',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Information Technology',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
    ])
