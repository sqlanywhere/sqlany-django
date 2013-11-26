from django.db.backends import BaseDatabaseIntrospection
from sqlanydb import ProgrammingError, OperationalError
import re
import sqlanydb


foreign_key_re = re.compile(r"\sCONSTRAINT `[^`]*` FOREIGN KEY \(`([^`]*)`\) REFERENCES `([^`]*)` \(`([^`]*)`\)")

class DatabaseIntrospection(BaseDatabaseIntrospection):
    data_types_reverse = { sqlanydb.DT_DATE         : 'DateField',
                           sqlanydb.DT_TIME         : 'DateTimeField',
                           sqlanydb.DT_TIMESTAMP    : 'DateTimeField',
                           sqlanydb.DT_VARCHAR      : 'CharField',
                           sqlanydb.DT_FIXCHAR      : 'CharField',
                           sqlanydb.DT_LONGVARCHAR  : 'CharField',
                           sqlanydb.DT_STRING       : 'CharField',
                           sqlanydb.DT_DOUBLE       : 'FloatField',
                           sqlanydb.DT_FLOAT        : 'FloatField',
                           sqlanydb.DT_DECIMAL      : 'IntegerField',
                           sqlanydb.DT_INT          : 'IntegerField',
                           sqlanydb.DT_SMALLINT     : 'IntegerField',
                           sqlanydb.DT_BINARY       : 'BlobField',
                           sqlanydb.DT_LONGBINARY   : 'BlobField',
                           sqlanydb.DT_TINYINT      : 'IntegerField',
                           sqlanydb.DT_BIGINT       : 'BigIntegerField',
                           sqlanydb.DT_UNSINT       : 'IntegerField',
                           sqlanydb.DT_UNSSMALLINT  : 'IntegerField',
                           sqlanydb.DT_UNSBIGINT    : 'BigIntegerField',
                           sqlanydb.DT_BIT          : 'IntegerField',
                           sqlanydb.DT_LONGNVARCHAR : 'CharField'
                           }

    def get_table_list(self, cursor):
        "Returns a list of table names in the current database."
        cursor.execute("SELECT table_name FROM sys.SYSTAB WHERE creator = USER_ID()")
        return [row[0] for row in cursor.fetchall()]

    def get_table_description(self, cursor, table_name):
        "Returns a description of the table, with the DB-API cursor.description interface."
        cursor.execute("SELECT FIRST * FROM %s" %
            self.connection.ops.quote_name(table_name))
        return tuple((c[0], t, None, c[3], c[4], c[5], int(c[6]) == 1) for c, t in cursor.columns())

    def _name_to_index(self, cursor, table_name):
        """
        Returns a dictionary of {field_name: field_index} for the given table.
        Indexes are 0-based.
        """
        return dict([(d[0], i) for i, d in enumerate(self.get_table_description(cursor, table_name))])

    def get_relations(self, cursor, table_name):
        """
        Returns a dictionary of {field_index: (field_index_other_table, other_table)}
        representing all relationships to the given table. Indexes are 0-based.
        """
        my_field_dict = self._name_to_index(cursor, table_name)
        constraints = []
        relations = {}
        cursor.execute("""
            SELECT (fidx.column_id - 1), t2.table_name, (pidx.column_id - 1) FROM SYSTAB t1
            INNER JOIN SYSFKEY f ON f.foreign_table_id = t1.table_id
            INNER JOIN SYSTAB t2 ON t2.table_id = f.primary_table_id
            INNER JOIN SYSIDXCOL fidx ON fidx.table_id = f.foreign_table_id AND fidx.index_id = f.foreign_index_id
            INNER JOIN SYSIDXCOL pidx ON pidx.table_id = f.primary_table_id AND pidx.index_id = f.primary_index_id
            WHERE t1.table_name = %s""", [table_name])
        constraints.extend(cursor.fetchall())

        for my_field_index, other_table, other_field_index in constraints:
            relations[my_field_index] = (other_field_index, other_table)

        return relations

    def get_indexes(self, cursor, table_name):
        """
        Returns a dictionary of fieldname -> infodict for the given table,
        where each infodict is in the format:
            {'primary_key': boolean representing whether it's the primary key,
             'unique': boolean representing whether it's a unique index}
        """
        # We need to skip multi-column indexes.
        cursor.execute("""
        select  max(c.column_name),
                max(ix.index_category),
                max(ix."unique")
        from    SYSIDX ix, SYSTABLE t, SYSIDXCOL ixc, SYSCOLUMN c
        where   ix.table_id = t.table_id
            and ixc.table_id = t.table_id
            and ixc.index_id = ix.index_id
            and ixc.table_id = c.table_id
            and ixc.column_id = c.column_id
            and t.table_name = %s
        group by ix.index_id
        having count(*) = 1
        order by ix.index_id
        """, [table_name])

        indexes = {}
        for col_name, cat, unique in cursor.fetchall():
            indexes[col_name] = {
                'primary_key': (cat == 1),
                'unique': (unique == 1 or unique == 2) }

        return indexes
