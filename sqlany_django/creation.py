import sys, traceback, time, re
from django.conf import settings
from django.db.backends.creation import BaseDatabaseCreation, TEST_DATABASE_PREFIX

try:
    import sqlanydb as Database
except ImportError, e:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Error loading sqlanydb module: %s" % e)

class DatabaseCreation(BaseDatabaseCreation):
    # This dictionary maps Field objects to their associated SQL Anywhere column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    data_types = {
        'AutoField':         'integer DEFAULT AUTOINCREMENT',
        'BooleanField':      'bit',
        'NullBooleanField':  'bit null',
        'CharField':         'varchar(%(max_length)s)',
        'CommaSeparatedIntegerField': 'varchar(%(max_length)s)',
        'DateField':         'date',
        'DateTimeField':     'datetime',
        'DecimalField':      'numeric(%(max_digits)s, %(decimal_places)s)',
        'FileField':         'varchar(%(max_length)s)',
        'FilePathField':     'varchar(%(max_length)s)',
        'FloatField':        'double precision',
        'IntegerField':      'integer',
        'BigIntegerField':   'bigint',
        'IPAddressField':    'char(15)',
        'GenericIPAddressField': 'char(39)',
        'OneToOneField':     'integer',
        'PositiveIntegerField': 'UNSIGNED integer',
        'PositiveSmallIntegerField': 'UNSIGNED smallint',
        'SlugField':         'varchar(%(max_length)s)',
        'SmallIntegerField': 'smallint',
        'TextField':         'text',
        'TimeField':         'time',
    }

    def sql_table_creation_suffix(self):
        suffix = []
        if settings.TEST_DATABASE_COLLATION:
            suffix.append('COLLATION %s' % settings.TEST_DATABASE_COLLATION)
        if settings.TEST_DATABASE_CHARSET:
            suffix.append('ENCODING %s' % settings.TEST_DATABASE_CHARSET)
        return ' '.join(suffix)

    def sql_db_start_suffix(self):
        return 'AUTOSTOP OFF'

    def sql_for_inline_foreign_key_references(self, field, known_models, style):
        """Don't use inline references for SQL Anywhere. This makes it
        easier to deal with conditionally creating UNIQUE constraints
        and UNIQUE indexes"""
        return [], True
        
    def sql_for_inline_many_to_many_references(self, model, field, style):
        from django.db import models
        opts = model._meta
        qn = self.connection.ops.quote_name
        
        table_output = [
            '    %s %s %s,' %
                (style.SQL_FIELD(qn(field.m2m_column_name())),
                style.SQL_COLTYPE(models.ForeignKey(model).db_type()),
                style.SQL_KEYWORD('NOT NULL')),
            '    %s %s %s,' %
            (style.SQL_FIELD(qn(field.m2m_reverse_name())),
            style.SQL_COLTYPE(models.ForeignKey(field.rel.to).db_type()),
            style.SQL_KEYWORD('NOT NULL'))
        ]
        deferred = [
            (field.m2m_db_table(), field.m2m_column_name(), opts.db_table,
                opts.pk.column),
            (field.m2m_db_table(), field.m2m_reverse_name(),
                field.rel.to._meta.db_table, field.rel.to._meta.pk.column)
            ]
        return table_output, deferred

    def _connect_to_utility_db(self):
        # Note: We don't use our standard double-quotes to "quote name"
        # a database name when creating a new database
        kwargs = {}
        links = {}
        settings_dict = self.connection.settings_dict
        if settings_dict['USER']:
            kwargs['uid'] = settings_dict['USER']
        kwargs['dbn'] = 'utility_db'
        if settings_dict['PASSWORD']:
            kwargs['pwd'] = settings_dict['PASSWORD']
        if settings_dict['HOST']:
            links['host'] = settings_dict['HOST']
        if settings_dict['PORT']:
            links['port'] = str(settings_dict['PORT'])
        kwargs.update(settings_dict['OPTIONS'])
        if len(links) > 0:
            kwargs['links'] = 'tcpip(' + ','.join(k+'='+v for k, v in links.items()) + ')'
        return Database.connect(**kwargs)

    def _create_test_db(self, verbosity, autoclobber):
        "Internal implementation - creates the test db tables."
        suffix = self.sql_table_creation_suffix()
        suffix_start = self.sql_db_start_suffix()

        test_database_name = self.connection.settings_dict['TEST_NAME']

        connection = self._connect_to_utility_db()
        cursor = connection.cursor()
        try:
            cursor.execute("CREATE DATABASE '%s' %s COLLATION 'UCA'" % (test_database_name, suffix))
            cursor.execute("START DATABASE '%s' %s" % (test_database_name, suffix_start))
        except Exception, e:
            traceback.print_exc()
            sys.stderr.write("Got an error creating the test database: %s\n" % e)
            if not autoclobber:
                confirm = raw_input("Type 'yes' if you would like to try deleting the test database '%s', or 'no' to cancel: " % test_database_name)
            if autoclobber or confirm == 'yes':
                try:
                    if verbosity >= 1:
                        print "Destroying old test database..."
                    cursor.execute("STOP DATABASE %s" % test_database_name)
                    cursor.execute("DROP DATABASE '%s'" % test_database_name)
                    if verbosity >= 1:
                        print "Creating test database..."
                    cursor.execute("CREATE DATABASE '%s' %s COLLATION 'UCA'" % (test_database_name, suffix))
                    cursor.execute("START DATABASE '%s' %s" % (test_database_name, suffix))
                except Exception, e:
                    sys.stderr.write("Got an error recreating the test database: %s\n" % e)
                    sys.exit(2)
            else:
                print "Tests cancelled."
                sys.exit(1)
        finally:
            cursor.close()
            connection.close()

        return test_database_name
        
    def _destroy_test_db(self, test_database_name, verbosity):
        "Internal implementation - remove the test db tables."
        # Remove the test database to clean up after
        # ourselves. Connect to the previous database (not the test database)
        # to do so, because it's not allowed to delete a database while being
        # connected to it.
        connection = self._connect_to_utility_db()
        cursor = connection.cursor()
        try:
            # Note: We don't use our standard double-quotes to "quote name"
            # a database name when droping a database
            cursor.execute("STOP DATABASE %s" % test_database_name)
            cursor.execute("DROP DATABASE '%s'" % test_database_name)
        except Exception, e:
            traceback.print_exc()
            sys.stderr.write("Got an error dropping test database: %s\n" % e)
        finally:
            cursor.close()
            connection.close()

    def _unique_swap(self, query, fields, model, style, table=None):
        """
        Fix unique constraints on multiple fields
        Build unique indexes instead of unique constraints

        Follows SQL generation from
        django.db.creation.BaseDatabaseCreation.sql_create_model
        """
        opts = model._meta
        qn = self.connection.ops.quote_name

        if table == None:
            table = opts.db_table

        fields_str = ", ".join([style.SQL_FIELD(qn(f)) for f in fields])
        multi_name = style.SQL_FIELD(qn("_".join(f for f in fields)))
        unique_str = 'UNIQUE (%s)' % fields_str
        unique_re_str = re.escape(unique_str) + '[,]?'
        query = re.sub(unique_re_str, '', query)
        
        idx_query = 'CREATE UNIQUE INDEX %s ON %s (%s);' % \
            (multi_name, style.SQL_FIELD(qn(table)), fields_str)
        return [query, idx_query]

    def _unique_swap_many(self, queries, fields, model, style, table=None):
        for i, query in enumerate(queries):
            changes = self._unique_swap(query, fields, model, style, table=table)
            if changes[0] != query:
                queries[i] = changes[0]
                queries.append(changes[1])
        
        return queries

    def sql_create_model(self, model, style, known_models=set()):
        """
        Returns the SQL required to create a single model, as a tuple of:
            (list_of_sql, pending_references_dict)
        """
        # Let BaseDatabaseCreation do most of the work
        opts = model._meta

        unique_nullable_fields = []

        for f in opts.local_fields:
            if f.unique and f.null:
                unique_nullable_fields.append(f)
                f._unique = False

        outputs, pending = super(DatabaseCreation,self).sql_create_model(model,style,known_models)
        qn = self.connection.ops.quote_name
        
        for f in unique_nullable_fields:
            f._unique = True
            outputs.append("CREATE UNIQUE INDEX %s on %s(%s);" % ("%s_%s_UNIQUE" % (opts.db_table, f.column), qn(opts.db_table), qn(f.column)))

        for field_constraints in opts.unique_together:
            fields = [opts.get_field(f).column for f in field_constraints]
            outputs = self._unique_swap_many(outputs, fields, model, style)

        return outputs, pending

    def sql_for_many_to_many_field(self, model, f, style):
        "Return the CREATE TABLE + CREATE UNIQUE INDEX statements for a single m2m field"
        # Let BaseDatabaseCreation do most of the work
        outputs = super(DatabaseCreation, self).sql_for_many_to_many_field(model, f, style)

        from django.db import models
        from django.db.backends.util import truncate_name

        if f.creates_table:
            opts = model._meta
            qn = self.connection.ops.quote_name
            fields = [f.m2m_column_name(), f.m2m_reverse_name()]
            outputs = self._unique_swap_many(outputs,
                                             fields,
                                             model,
                                             style,
                                             table=f.m2m_db_table())
        
        return outputs
