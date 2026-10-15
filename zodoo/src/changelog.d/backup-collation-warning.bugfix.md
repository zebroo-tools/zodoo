The database backup no longer fails on postgres' "collation version mismatch"
warning. Since the postgres images moved to bookworm (glibc 2.36), databases
created under bullseye (glibc 2.31) print it on every connection, and the backup
treated any stderr output as fatal - hosts with a rebuilt postgres container got
no nightly dump at all. The warning is now logged with a hint to run REINDEX and
`ALTER DATABASE ... REFRESH COLLATION VERSION`; every other stderr output still
fails the backup.
