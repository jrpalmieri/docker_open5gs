# Instructions for running SA core on docket

## start the SA containers only
`docker compose -f sa-deploy.yaml up`

file .env has network address assignments for each NF container.

## to reach the docker network, gnbs must have addresses on the docker network
`sudo ip addr add <docker_net_addr>/24 dev <name of docker_net_bridge> (use ip addr show to find)`

### example
sudo ip addr add 172.22.0.201/24 dev br-83331057c451
where gnb has its ngapIP and gtpIp assignd to 172.22.0.201