from django import VERSION as djangoVersion

if djangoVersion[:2] >= (1, 8):
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
else:
    from django.db.backends.schema import BaseDatabaseSchemaEditor

class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):

    # Overrideable SQL templates
    sql_rename_table = "ALTER TABLE %(old_table)s RENAME %(new_table)s"
    sql_retablespace_table = None
    sql_create_column = "ALTER TABLE %(table)s ADD %(column)s %(definition)s"
    sql_alter_column_type = "ALTER %(column)s %(type)s"
    sql_alter_column_null = "ALTER %(column)s NULL"
    sql_alter_column_not_null = "ALTER %(column)s NOT NULL"
    sql_alter_column_default = "ALTER %(column)s DEFAULT %(default)s"
    sql_alter_column_no_default = "ALTER %(column)s DROP DEFAULT"
    sql_delete_column = "ALTER TABLE %(table)s DROP %(column)s"
    sql_rename_column = "ALTER TABLE %(table)s RENAME %(old_column)s TO %(new_column)s"
    sql_update_with_default = "UPDATE %(table)s SET %(column)s = %(default)s WHERE %(column)s IS NULL"

    sql_create_fk = "ALTER TABLE %(table)s ADD CONSTRAINT %(name)s FOREIGN KEY (%(column)s) REFERENCES %(to_table)s (%(to_column)s)"
    sql_delete_fk = "ALTER TABLE %(table)s DROP CONSTRAINT %(name)s"

    def alter_db_tablespace(self, model, old_db_tablespace, new_db_tablespace):
        """
        Moves a model's table between tablespaces
        - not applicable to SQL Anywhere
        """
        pass
#
