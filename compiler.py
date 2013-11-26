import re

from django.db.models.sql import compiler

# Cache classes that have already been built
_classes = {}
select_re = re.compile('^SELECT[ ]+(DISTINCT\s)?')

class SQLCompiler(compiler.SQLCompiler):
    def as_sql(self, with_limits=True, with_col_aliases=True):
        query, params = super(SQLCompiler, self).as_sql(with_limits=False, 
                                                        with_col_aliases=with_col_aliases)
        m = select_re.match(query)
        if with_limits and m != None:
            num = None
            insert = None
            if self.query.high_mark is not None:
                num = self.query.high_mark - self.query.low_mark
                if num <= 0:
                    return None, None
                insert = 'TOP %d' % num
            if self.query.low_mark:
                if insert is None:
                    insert = 'TOP ALL'
                insert = '%s START AT %d' % (insert, self.query.low_mark + 1)
            if insert is not None:
                if m.groups()[0] != None:
                    query = select_re.sub('SELECT DISTINCT %s ' % insert, query)
                else:
                    query = select_re.sub('SELECT %s ' % insert, query)
        return query, params

class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    pass

class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    pass

class SQLUpdateCompiler(compiler.SQLUpdateCompiler, SQLCompiler):
    pass

class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass

class SQLDateCompiler(compiler.SQLDateCompiler, SQLCompiler):
    pass
