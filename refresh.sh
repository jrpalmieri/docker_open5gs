#!/bin/bash

# clears all runtime state from the mongo db
#  but preserves the subscriber information

# Define the container name for MongoDB as per your YAML
MONGO_CONTAINER="mongo"
LOG_DIR="./log"

echo "--- Starting Open5GS Testbed Reset ---"

# 1. Stop all Network Function containers (but keep Mongo running to wipe it)
echo "Stopping Open5GS Network Functions..."
docker compose -f ./sa-deploy.yaml stop amf smf upf nrf scp ausf udr udm pcf bsf nssf

# 2. Clear Runtime State in MongoDB (Preserving Subscribers)
echo "Surgically wiping session and AMF state from MongoDB..."
docker exec -it $MONGO_CONTAINER mongosh open5gs --eval '
  const protect = ["subscribers", "profiles", "system.indexes"];
  db.getCollectionNames().forEach(col => {
    if (!protect.includes(col)) {
      print("Wiping collection: " + col);
      db[col].deleteMany({});
    }
  });
'

# 3. Clear the log files to keep the next test run clean
if [ -d "$LOG_DIR" ]; then
    echo "Clearing old log files..."
    sudo rm -f $LOG_DIR/*.log
fi

# 4. Restart the Core
echo "Restarting Open5GS stack..."
docker compose -f ./sa-deploy.yaml start

echo "--- Reset Complete. Subscriber profiles not impacted. ---"