#!/bin/sh
set -e

exit_backend() {
  echo "Exiting backend"
  python3 4cat-daemon.py stop
  exit 0
}

trap exit_backend INT TERM

# Handle any options
while test $# != 0
do
    case "$1" in
    -p ) # set public option to use public IP address as SERVER_NAME
        echo 'Setting SERVER_NAME to public IP'
        SERVER_NAME=$(curl -s https://api.ipify.org);;
    -h ) # set public option to use server hostname as SERVER_NAME
        echo 'Setting SERVER_NAME to server hostname'
        SERVER_NAME=$(hostnamectl --static);;
    * )  # Invalid option
        echo "Error: Invalid option"
        exit;;
    esac
    shift
done

echo "Waiting for postgres..."
while ! nc -z $POSTGRES_HOST $POSTGRES_PORT; do
  sleep 0.1
done
echo "PostgreSQL started"

if [ -n "$MEMCACHED_HOST" ] || [ -n "$MEMCACHED_PORT" ]; then
  echo "Waiting for memcached..."
  while ! nc -z ${MEMCACHED_HOST:-memcached} ${MEMCACHED_PORT:-11211}; do
    sleep 0.1
  done
  echo "Memcached started"
fi

# Create Database if it does not already exist
if [ `psql --host=$POSTGRES_HOST --port=$POSTGRES_PORT --user=$POSTGRES_USER --dbname=$POSTGRES_DB -tAc "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'jobs')"` = 't' ]; then
  # Table already exists
  echo "Database already created"
else
  echo "Creating Database"
  # Seed DB
  cd /usr/src/app && psql --host=$POSTGRES_HOST --port=$POSTGRES_PORT --user=$POSTGRES_USER --dbname=$POSTGRES_DB < backend/database.sql
  # No database exists, new build, no need to migrate so create .current-version file
  mkdir -p config && cp VERSION config/.current-version
fi

# If backend did gracefully shutdown, PID lockfile remains; Remove lockfile
rm -f ./backend/4cat.pid

# add working directory to python path
export PYTHONPATH=/usr/src/app:$PYTHONPATH

# Run migrate prior to setup (old builds pre 1.26 may not have config_manager)
python3 helper-scripts/migrate.py -y -o data/logs/migrate-backend.log

# Run docker_setup to update any environment variables if they were changed
python3 -m docker.docker_setup

# Start 4CAT backend
python3 4cat-daemon.py start

# Tail logs and wait for SIGTERM
sleep 1  # give the logger time to initialise
# get log location from python config.get("PATH_LOGS") as it is more reliable than hardcoding
log_file=$(python3 -c "from common.config_manager import CoreConfigManager; config = CoreConfigManager(); print(config.get('PATH_LOGS').joinpath('backend_4cat.log'));")
exec tail -f -n 3 ${log_file} & wait $!