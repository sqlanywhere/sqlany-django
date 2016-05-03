"""
SQL Anywhere database backend for Django.

Requires sqlanydb
"""

import re,ctypes,sys

try:
    import sqlanydb as Database
except ImportError as e:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Error loading sqlanydb module: %s" % e)

from django import VERSION as djangoVersion

if djangoVersion[:2] >= (1, 4):
    from django.utils.timezone import is_aware, is_naive, utc, make_naive, make_aware, get_default_timezone
    import datetime

from django.conf import settings
if djangoVersion[:2] >= (1, 8):
    from django.db.backends.base.features import BaseDatabaseFeatures
    from django.db.backends.base.operations import BaseDatabaseOperations
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.backends import utils as util
else:
    from django.db.backends import *
    if djangoVersion[:2] >= (1, 7):
        # renamed in 1.7
        util = utils
from django.db.backends.signals import connection_created
from sqlany_django.client import DatabaseClient
from sqlany_django.creation import DatabaseCreation
from sqlany_django.introspection import DatabaseIntrospection
from sqlany_django.validation import DatabaseValidation
if djangoVersion[:2] >= (1, 7):
    from sqlany_django.schema import DatabaseSchemaEditor
if djangoVersion[:2] >= (1, 8):
    from sqlany_django.creation import global_data_types

DatabaseError = Database.DatabaseError
IntegrityError = Database.IntegrityError

Database.register_converter(Database.DT_TIMESTAMP, util.typecast_timestamp)
Database.register_converter(Database.DT_DATE, util.typecast_date)
Database.register_converter(Database.DT_TIME, util.typecast_time)
Database.register_converter(Database.DT_DECIMAL, util.typecast_decimal)
Database.register_converter(Database.DT_BIT, lambda x: x if x is None else bool(x))

def trace(x):
    # print( x )
    return x

def _datetimes_in(args):
    def fix(arg):
        if isinstance(arg, datetime.datetime):
            if is_naive(arg):
                warnings.warn("Received a naive datetime (%s) while timezone support is active." % arg, RuntimeWarning)
                arg = make_aware(arg, timezone.get_default_timezone())
            arg = arg.astimezone(utc).replace(tzinfo=None)
        return arg

    return tuple(fix(arg) for arg in args)

class CursorWrapper(object):
    """
    A thin wrapper around sqlanydb's normal cursor class so that we can catch
    particular exception instances and reraise them with the right types.

    Implemented as a wrapper, rather than a subclass, so that we aren't stuck
    to the particular underlying representation returned by Connection.cursor().
    """
    codes_for_integrityerror = (1048,)

    def __init__(self, cursor):
        self.cursor = cursor

    def __del__(self):
        if self.cursor:
            self.cursor.close()
            self.cursor = None

    def convert_query(self, query, num_params):
        """
        Django uses "format" style placeholders, but SQL Anywhere uses "qmark" style.
        This fixes it -- but note that if you want to use a literal "%s" in a query,
        you'll need to use "%%s".
        """
        return query if num_params == 0 else query % tuple("?" * num_params)

    def execute(self, query, args=()):
        if djangoVersion[:2] >= (1, 4) and settings.USE_TZ:
            args = _datetimes_in(args)
        try:
            if args != None:
                query = self.convert_query(query, len(args))
            ret = self.cursor.execute(trace(query), trace(args))
            return ret
        except Database.OperationalError as e:
            if e.message == 'Connection was terminated':
                from django import db
                try:
                    db.close_old_connections()
                except AttributeError:
                    db.close_connection()
            # Map some error codes to IntegrityError, since they seem to be
            # misclassified and Django would prefer the more logical place.
            if e.errorcode in self.codes_for_integrityerror:
                raise Database.IntegrityError(e)
            raise

    def executemany(self, query, args):
        if djangoVersion[:2] >= (1, 4) and settings.USE_TZ:
            args = tuple(_datetimes_in(arg) for arg in args)
        try:
            try:
                len(args)
            except TypeError:
                args = tuple(args)
            if len(args) > 0:
                query = self.convert_query(query, len(args[0]))
                ret = self.cursor.executemany(trace(query), trace(args))
                return trace(ret)
            else:
                return None
        except Database.OperationalError as e:
            # Map some error codes to IntegrityError, since they seem to be
            # misclassified and Django would prefer the more logical place.
            if e.errorcode in self.codes_for_integrityerror:
                raise Database.IntegrityError(e)
            raise

    def fetchone(self):
        if djangoVersion[:2] < (1, 4) or not settings.USE_TZ:
            return trace(self.cursor.fetchone())
        return self._datetimes_out(self.cursor.fetchone())

    def fetchmany(self, size=0):
        if djangoVersion[:2] < (1, 4) or not settings.USE_TZ:
            return trace(self.cursor.fetchmany(size))
        rows = self.cursor.fetchmany(size)
        return list(self._datetimes_out(row) for row in rows)

    def fetchall(self):
        if djangoVersion[:2] < (1, 4) or not settings.USE_TZ:
            return trace(self.cursor.fetchall())
        return list(self._datetimes_out(row) for row in self.cursor.fetchall())

    def _datetimes_out(self, row):
        def fix(item):
            value, desc = item
            if desc[1] == Database.DATETIME:
                if value is not None and is_naive(value):
                    value = value.replace(tzinfo=utc)
            return value

        if row is None:
            return row

        return trace(tuple(fix(item) for item in zip(row, self.cursor.description)))

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        else:
            return getattr(self.cursor, attr)

    def __iter__(self):
        return iter(self.fetchall())

class DatabaseFeatures(BaseDatabaseFeatures):
    allows_group_by_pk = False
    empty_fetchmany_value = []
    has_bulk_insert = True
    has_select_for_update = True
    has_zoneinfo_database = False
    related_fields_match_type = True
    supports_regex_backreferencing = False
    supports_sequence_reset = False
    update_can_self_select = False
    uses_custom_query_class = False

class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = "sqlany_django.compiler"

    def bulk_insert_sql(self, fields, num_values):
        items_sql = "(%s)" % ", ".join(["%s"] * len(fields))
        return "VALUES " + ", ".join([items_sql] * num_values)

    def date_extract_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month' or 'day', returns the SQL that
        extracts a value from the given date field field_name.
        """
        if lookup_type == 'week_day':
            # Returns an integer, 1-7, Sunday=1
            return "DATEFORMAT(%s, 'd')" % field_name
        else:
            # YEAR(), MONTH(), DAY() functions
            return "%s(%s)" % (lookup_type.upper(), field_name)

    if djangoVersion[:2] >= (1, 8):
        # SQL Anywhere does not support the INTERVAL syntax
        pass
        #def date_interval_sql(self, timedelta):
    else:
        def date_interval_sql(self, sql, connector, timedelta):
            """
            Implements the date interval functionality for expressions
            """
            return 'DATEADD(day, %s(%d), DATEADD(second, %s(%d), DATEADD(microsecond, %s(%d), %s)))' % (connector, timedelta.days, connector, timedelta.seconds, connector, timedelta.microseconds, sql)

    def date_trunc_sql(self, lookup_type, field_name):
        """
        Given a lookup_type of 'year', 'month' or 'day', returns the SQL that
        truncates the given date field field_name to a DATE object with only
        the given specificity.
        """
        fields = ['year', 'month', 'day', 'hour', 'minute', 'second']
        format = ('YYYY-', 'MM', '-DD', 'HH:', 'NN', ':SS') # Use double percents to escape.
        format_def = ('0000-', '01', '-01', ' 00:', '00', ':00')
        try:
            i = fields.index(lookup_type) + 1
        except ValueError:
            sql = field_name
        else:
            format_str = ''.join([f for f in format[:i]] + [f for f in format_def[i:]])
            sql = "CAST(DATEFORMAT(%s, '%s') AS DATETIME)" % (field_name, format_str)
        return sql

    def datetime_extract_sql(self, lookup_type, field_name, tzname):
        """
        Given a lookup_type of 'year', 'month', 'day', 'hour', 'minute' or
        'second', returns the SQL that extracts a value from the given
        datetime field field_name, and a tuple of parameters.
        """
        if lookup_type == 'week_day':
            # Returns an integer, 1-7, Sunday=1
            sql = "DATEFORMAT(%s, 'd')" % field_name
        else:
            # YEAR(), MONTH(), DAY(), HOUR(), MINUTE(), SECOND() functions
            sql = "%s(%s)" % (lookup_type.upper(), field_name)
        return sql,[]

    def datetime_trunc_sql(self, lookup_type, field_name, tzname):
        """
        Given a lookup_type of 'year', 'month', 'day', 'hour', 'minute' or
        'second', returns the SQL that truncates the given datetime field
        field_name to a datetime object with only the given specificity, and
        a tuple of parameters.
        """
        fields = ['year', 'month', 'day', 'hour', 'minute', 'second']
        format = ('YYYY-', 'MM', '-DD', 'HH:', 'NN', ':SS') # Use double percents to escape.
        format_def = ('0000-', '01', '-01', ' 00:', '00', ':00')
        try:
            i = fields.index(lookup_type) + 1
        except ValueError:
            sql = field_name
        else:
            format_str = ''.join([f for f in format[:i]] + [f for f in format_def[i:]])
            sql = "CAST(DATEFORMAT(%s, '%s') AS DATETIME)" % (field_name, format_str)
        return sql,[]

    def deferrable_sql(self):
        return ""

    def drop_foreignkey_sql(self):
        """
        Returns the SQL command that drops a foreign key.
        """
        # This will work provided it is inserted in an ALTER TABLE statement
        return "DROP FOREIGN KEY"

    def force_no_ordering(self):
        """
        "ORDER BY NULL" prevents SQL Anywhere from implicitly ordering by grouped
        columns. If no ordering would otherwise be applied, we don't want any
        implicit sorting going on.
        """
        return ["NULL"]

    def fulltext_search_sql(self, field_name):
        """
        Returns the SQL WHERE clause to use in order to perform a full-text
        search of the given field_name. Note that the resulting string should
        contain a '%s' placeholder for the value being searched against.
        """
        return 'CONTAINS(%s, %%s)' % field_name

    def last_insert_id(self, cursor, table_name, pk_name):
        cursor.execute('SELECT @@identity')
        return cursor.fetchone()[0]
    
    def max_name_length(self):
        """
        Returns the maximum length of table and column names, or None if there
        is no limit.
        """
        # SQL Anywhere 11 has a maximum of 128 for table and column names
        return 128

    def no_limit_value(self):
        """
        Returns the value to use for the LIMIT when we are wanting "LIMIT
        infinity". Returns None if the limit clause can be omitted in this case.
        """
        return None
    
    def prep_for_iexact_query(self, x):
        return x

    def query_class(self, DefaultQueryClass):
        """
        Given the default Query class, returns a custom Query class
        to use for this backend. Returns None if a custom Query isn't used.
        See also BaseDatabaseFeatures.uses_custom_query_class, which regulates
        whether this method is called at all.
        """
        return query.query_class(DefaultQueryClass)

    def quote_name(self, name):
        """
        Returns a quoted version of the given table, index or column name. Does
        not quote the given name if it's already been quoted.
        """
        if name.startswith('"') and name.endswith('"'):
            return name # Quoting once is enough.
        return '"%s"' % name

    def regex_lookup(self, lookup_type):
        """
        Returns the string to use in a query when performing regular expression
        lookups (using "regex" or "iregex"). The resulting string should
        contain a '%s' placeholder for the column being searched against.
        """
        if lookup_type == 'iregex':
            raise NotImplementedError("SQL Anywhere does not support case insensitive regular expressions")
        return "%s REGEXP ('.*'||%s||'.*')"

    def random_function_sql(self):
        """
        Returns a SQL expression that returns a random value.
        """
        return 'RAND()'

    def savepoint_create_sql(self, sid):
        """
        Returns the SQL for starting a new savepoint. Only required if the
        "uses_savepoints" feature is True. The "sid" parameter is a string
        for the savepoint id.
        """
        return 'SAVEPOINT ' + self.quote_name(sid)

    def savepoint_commit_sql(self, sid):
        """
        Returns the SQL for committing the given savepoint.
        """
        return 'COMMIT'

    def savepoint_rollback_sql(self, sid):
        """
        Returns the SQL for rolling back the given savepoint.
        """
        return 'ROLLBACK TO SAVEPOINT ' + self.quote_name(sid)

    def sql_flush(self, style, tables, sequences):
        """
        Returns a list of SQL statements required to remove all data from
        the given database tables (without actually removing the tables
        themselves).
        """
        if tables:
            sql = ['SET TEMPORARY OPTION wait_for_commit = \'On\';']
            # TODO: We should truncate tables here, but there may cause an error;
            # for now, delete (all) from each table
            for table in tables:
                sql.append('DELETE FROM %s;' % self.quote_name(table))

            # TODO: This requires DBA authority, but once the truncate bug is fixed
            # it won't be necessary
            for sequence in sequences:
                sql.append('call sa_reset_identity(\'%s\', NULL, 0);' % sequence['table'])
            
            sql.append('SET TEMPORARY OPTION wait_for_commit = \'Off\';')
            sql.append('COMMIT;')
            
            return sql

    def value_to_db_datetime(self, value):
        if value is None:
            return None

        if djangoVersion[:2] <= (1, 3):
            # SQL Anywhere doesn't support tz-aware datetimes
            if value.tzinfo is not None:
                raise ValueError("SQL Anywhere backend does not support timezone-aware datetimes.")
        else:
            if is_aware(value):
                if settings.USE_TZ:
                    value = value.astimezone(utc).replace(tzinfo=None)
                else:
                    make_naive(value, get_default_timezone())
    
        return str(value)

    def value_to_db_time(self, value):
        if value is None:
            return None

        if djangoVersion[:2] <= (1, 3):
            # SQL Anywhere doesn't support tz-aware datetimes
            if value.tzinfo is not None:
                raise ValueError("SQL Anywhere backend does not support timezone-aware datetimes.")
        else:
            if is_aware(value):
                make_naive(value, get_default_timezone())
    
        return str(value)

class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'sqlanywhere'
    operators = {
        'exact': '= %s',
        'iexact': '= %s',
        'contains': "LIKE %s ESCAPE '\\'",
        'icontains': "LIKE %s ESCAPE '\\'",
        'regex': "REGEXP ('.*'||%s||'.*')",
        # 'iregex': "REGEXP ('.*'||%s||'.*')",
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': "LIKE %s ESCAPE '\\'",
        'istartswith': "LIKE %s ESCAPE '\\'",
        'endswith': "LIKE %s ESCAPE '\\'",
        'iendswith': "LIKE %s ESCAPE '\\'"
    }
    if djangoVersion[:2] >= (1, 8):
        # Moved from DatabaseCreation in 1.8
        data_types = global_data_types

    Database = Database
    
    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)

        self.server_version = None
        if djangoVersion[:2] >= (1, 3):
            self.features = DatabaseFeatures(self)
        else:
            self.features = DatabaseFeatures()
        if djangoVersion[:2] >= (1, 4):
            self.ops = DatabaseOperations(self)
        else:
            self.ops = DatabaseOperations()
        self.client = DatabaseClient(self)
        self.creation = DatabaseCreation(self)
        self.introspection = DatabaseIntrospection(self)
        if djangoVersion[:2] >= (1, 2):
            self.validation = DatabaseValidation(self)
        else:
            self.validation = DatabaseValidation()

    def _valid_connection(self):
        if self.connection is not None:
            try:
                self.connection.con()
                return True
            except InterfaceError:
                self.connection.close()
                self.connection = None
        return False

    def check_constraints(self, table_names=None):
        self.cursor().execute('PREPARE TO COMMIT')

    def _cursor(self):
        return self.create_cursor()

    def _rollback(self):
        try:
            BaseDatabaseWrapper._rollback(self)
        except Database.NotSupportedError:
            pass

    # New methods for Django 1.6
    def get_connection_params(self):
        kwargs = {}
        links = {}

        settings_dict = self.settings_dict

        def setting( key ):
            if key in settings_dict:
                return settings_dict[key]
            dbkey = 'DATABASE_%s' % key
            if dbkey in settings_dict:
                return settings_dict[dbkey]
            return None
        #
        
        def empty( s ):
            return True if ( s is None or s == '' ) else False
        #

        uid = setting( 'USER' )
        if not empty( uid ):
            kwargs['uid'] = uid
        dbn = setting( 'NAME' )
        if not empty( dbn ):
            kwargs['dbn'] = dbn
        pwd = setting( 'PASSWORD' )
        if not empty( pwd ):
            kwargs['pwd'] = pwd

        root = Database.Root('PYTHON')

        try:
            vers = root.api.sqlany_client_version()
            ret = True
        except:
            length = 1000
            buffer = ctypes.create_string_buffer(length)
            ret = root.api.sqlany_client_version(ctypes.byref(buffer), length)
            vers = buffer.value
        if ret:
            if sys.version_info[0] >= 3:
                # Python 3: convert bytes to str
                vers = str(vers, 'utf-8')
            vers = int(vers.split('.')[0])
        else:
            vers = 11 # assume old
        host = setting( 'HOST' )
        if host == '':
            host = 'localhost' # "Set to empty string for localhost"
        if not empty( host ) and vers > 11:
            kwargs['host'] = host
            port = setting( 'PORT' )
            if not empty( port ):
                kwargs['host'] += ':%s' % port
        else:
            if not empty( host ):
                links['host'] = host
            port = setting( 'PORT' )
            if not empty( port ):
                links['port'] = str( port )
        if len(links) > 0:
            kwargs['links'] = 'tcpip(' + ','.join(k+'='+v for k, v in list(links.items())) + ')'
        kwargs.update(setting( 'OPTIONS' ))
        return kwargs

    def get_new_connection( self, conn_params ):
        conn = Database.connect(**conn_params)
        if conn is not None and djangoVersion[:2] >= (1, 6):
            # Autocommit is the default for 1.6+
            curs = conn.cursor()
            curs.execute( "SET TEMPORARY OPTION chained='Off'" )
            curs.close()
        return conn
        
    def init_connection_state( self ):
        if 'AUTOCOMMIT' in self.settings_dict and \
           not self.settings_dict['AUTOCOMMIT']:
            self.set_autocommit( False )

    def create_cursor( self ):
        cursor = None
        if not self._valid_connection():
            kwargs = self.get_connection_params()
            self.connection = self.get_new_connection(kwargs)
            cursor = CursorWrapper(self.connection.cursor())
            if djangoVersion[:2] < (1, 2):
                cursor.execute("SET TEMPORARY OPTION PUBLIC.reserved_keywords='LIMIT'")
            cursor.execute("SET TEMPORARY OPTION TIMESTAMP_FORMAT='YYYY-MM-DD HH:NN:SS.SSSSSS'")
            connection_created.send(sender=self.__class__, connection=self)
        if not cursor:
            cursor = CursorWrapper(self.connection.cursor())

        return cursor

    def _set_autocommit( self, autocommit ):
        """
        Backend-specific implementation to enable or disable autocommit.
        """
        curs = self.create_cursor()
        curs.execute( "SET TEMPORARY OPTION chained='%s'" %
                      ('Off' if autocommit else 'On') )
        curs.close()

    def is_usable(self):
        """
        Tests if the database connection is usable.
        This function may assume that self.connection is not None.
        """
        return self._valid_connection()

    # New methods for Django 1.7
    if djangoVersion[:2] >= (1, 7):
        def schema_editor(self, *args, **kwargs):
            "Returns a new instance of this backend's SchemaEditor"
            return DatabaseSchemaEditor( self, *args, **kwargs )
        
#
