#!/usr/bin/env python
# ***************************************************************************
# Copyright (c) 2013 SAP AG or an SAP affiliate company. All rights reserved.
# ***************************************************************************

r"""sqlany-django - SQL Anywhere driver for Django.

https://github.com/sqlanywhere/sqlany-django

----------------------------------------------------------------"""

from setuptools import setup, find_packages
import os,re

with open( os.path.join( os.path.dirname(__file__), 'sqlany_django',
                         '__init__.py' ) ) as v:
    VERSION = re.compile(r".*__version__ = '(.*?)'", re.S).match(v.read()).group(1)

setup(name='sqlany_django',
      version=VERSION,
      description='SQL Anywhere database backend for Django',
      long_description=open('README.rst').read(),
      author='Graeme Perrow',
      author_email='graeme.perrow@sap.com',
      install_requires=['sqlanydb >= 1.0.4'],
      url='https://github.com/sqlanywhere/sqlany-django',
      packages=find_packages(),
      license='New BSD',
      classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Framework :: Django',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.4',
        'Programming Language :: Python :: 2.5',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.0',
        'Programming Language :: Python :: 3.1',
        'Programming Language :: Python :: 3.2',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Topic :: Database',
        'Topic :: Software Development :: Libraries :: Python Modules'
        ]
      )
