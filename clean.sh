#!/usr/bin/env bash
#sudo chmod 666 /var/run/docker.sock
	
## sudo chown -R 5050:5050 ~/volumes/data/pgbackup/_data/pgadmin
docker rm -f $(docker ps -a -q)
docker rmi $(docker images | grep "^<none>" | awk "{print $3}")
docker ps -a
