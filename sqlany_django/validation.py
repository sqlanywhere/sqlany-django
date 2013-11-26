from django.db.backends import BaseDatabaseValidation

class DatabaseValidation(BaseDatabaseValidation):
    def validate_field(self, errors, opts, f):
        from django.db import models
        from django.db import connection
        varchar_fields = (models.CharField, models.CommaSeparatedIntegerField,
                models.SlugField)
        # TODO: We should check for UTF8
        # For varchar maximum, specs say single-byte:32767, double-byte:16383, utf8:8191
        if isinstance(f, varchar_fields) and f.max_length > 8191:
            msg = '"%(name)s": %(cls)s cannot have a "max_length" greater than 8191'
            if msg:
                errors.add(opts, msg % {'name': f.name, 'cls': f.__class__.__name__})

