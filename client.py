from django.db.backends import BaseDatabaseClient
from django.conf import settings
import os

class DatabaseClient(BaseDatabaseClient):
    executable_name = 'dbisqlc'

    def runshell(self):
        conn_str = []
        
        if settings.DATABASE_NAME:
            conn_str.append("dbn=%s" % settings.DATABASE_NAME)
        if settings.DATABASE_USER:
            conn_str.append("uid=%s" % settings.DATABASE_USER)
        if settings.DATABASE_PASSWORD:
            conn_str.append("pwd=%s" % settings.DATABASE_PASSWORD)
        if settings.DATABASE_HOST:
            tmp = "links=tcpip(host=%s" % settings.DATABASE_HOST
            if settings.DATABASE_PORT:
                tmp += ";port=%s" % settings.DATABASE_PORT
            tmp += ")"
            conn_str.append(tmp)
        for k,v in settings.DATABASE_OPTIONS:
            conn_str.append("%s=%s" % (k,v))

        args = [self.executable_name]
        if len(conn_str):
            args.append( '-c' )
            args.append( ';'.join(conn_str) )

        os.execvp(self.executable_name,args)
