from flask import Flask, request, jsonify
import json
import requests
from flask_cors import CORS
import os
import string
import random
import sys
import threading
import time
import mysql.connector

sys.path.append('../utils')
from hashring import HashRing

app = Flask(__name__)
CORS(app)
replica_lock = threading.Lock() # Lock for the replicas list
shard_to_hr = {} # This dictionary will map the shard_id to hashring. key: shard_id, value: (hashring)
shard_to_hrlock = {} # Lock for the shard_to_hr dictionary

'''
This function is called when a new server is added to the load balancer. It creates a new container with the server image and adds it to the hashring.
'''
def add_servers(n, shard_mapping, mycursor):
    # global num_servers
    global replicas

    hostnames = []
    for server, shards_list in shard_mapping:
        # append only the server name to the hostnames list
        hostnames.append(server)
    
    replica_names = []
    replica_lock.acquire()
    for replica in replica_names:
        replica_names.append(replica[0])

    # We go through the list of preferred hostnames and check if the hostname already exists, or if no hostname is provided, we generate a random hostname   
    for i in range(n):
        if (i >= len(hostnames)) or (hostnames[i] in replica_names):
            for j in range(len(replica_names)+1):
                new_name = 'S'+ str(j)
                if new_name not in replica_names:
                    hostnames.append(new_name)
                    replica_names.append(new_name)
                    break
        elif hostnames[i] not in replica_names:
            replica_names.append(hostnames[i])
    # Spawn the containers from the load balancer
    for i in range(n):
        container_name = "Server_"
        serverid = -1
        # Allocate the first free server ID between 1 and num_servers
        if len(server_ids) == 0:
            global next_server_id
            serverid = next_server_id
            next_server_id += 1
        else:
            serverid = min(server_ids)
            server_ids.remove(min(server_ids))
        # Generate the container name: Server_<serverid>
        container_name += str(serverid)
        container = os.popen(f'docker run --name {container_name} --network mynet --network-alias {container_name} -e SERVER_ID={serverid} -d serverim:latest').read()
        if len(container) != 0:
            replicas.append([hostnames[i], container_name])
            # Configure the server with the shards
            shards_list = shard_mapping[hostnames[i]]
            shards_list = json.dumps(shards_list)
            # sort the shards list to avoid deadlocks when later shard locks are acquired
            shards_list = sorted(shards_list)
            try:
                reply = requests.post(f'http://{container_name}:{serverport}/config', 
                                      json = {
                                            "schema": studT_schema,
                                            "shards": shards_list
                                      })
            except requests.exceptions.ConnectionError:
                replica_lock.release()
                return jsonify({'message': 'Server configuration failed', 'status': 'failure'}), 400
            if reply.status_code != 200:
                replica_lock.release()
                return jsonify({'message': 'Server configuration failed', 'status': 'failure'}), 400
            for shard in shards_list:
                mycursor.execute(f"INSERT INTO MapT (Shard_id, Server_id) VALUES ({shard}, {serverid})")
                # Add the server to the hashring
                shard_to_hrlock[shard].acquire()
                shard_to_hr[shard].add_server(container_name)
                shard_to_hrlock[shard].release()

        else:
            replica_lock.release()
            return jsonify({'message': 'Server creation failed', 'status': 'failure'}), 400 
    replica_lock.release()
    # num_servers += n
    return jsonify({'message': 'Servers spawned and configured', 'status': 'success'}), 200
    
'''
(/init, method=POST): This endpoint initializes the distributed database across different shards and replicas in  the  server  containers
Sample Payload:
{
    "N":3
    "schema":{"columns":["Stud_id","Stud_name","Stud_marks"],"dtypes":["Number","String","String"]}
    "shards":[{"Stud_id_low":0, "Shard_id": "sh1", "Shard_size":4096},
              {"Stud_id_low":4096, "Shard_id": "sh2", "Shard_size":4096},
              {"Stud_id_low":8192, "Shard_id": "sh3", "Shard_size":4096},]
    "servers":{"Server0":["sh1","sh2"],
               "Server1":["sh2","sh3"],
               "Server2":["sh1","sh3"]}
}

Sample response:
{
    "message": "Configured Database",
    "status": "success"
}    
'''
@app.route('/init', methods=['POST'])
def init():
    content = request.get_json(force=True)
    n = content['N'] # Number of servers
    global studT_schema
    studT_schema = content['schema'] # Schema of the database
    shards = content['shards'] # Shards with Stud_id_low, Shard_id, Shard_size
    shard_mapping = content['servers'] # Servers with Shard_id

    # global num_servers
    # num_servers = n

    # Sanity check
    if len(shard_mapping) != n:
        message = '<ERROR> Number of servers does not match the number of servers provided'
        return jsonify({'message': message, 'status': 'failure'}), 400
    
    # Sanity check
    for server, shards_list in shard_mapping:
        if len(shards_list) == 0:
            message = '<ERROR> No shards assigned to server'
            return jsonify({'message': message, 'status': 'failure'}), 400
        
    # Sanity check
    for shard in shards:
        if shard['Stud_id_low'] < 0:
            message = '<ERROR> Stud_id_low cannot be negative'
            return jsonify({'message': message, 'status': 'failure'}), 400
        if shard['Shard_size'] <= 0:
            message = '<ERROR> Shard_size cannot be non-positive'
            return jsonify({'message': message, 'status': 'failure'}), 400
    
    # Initialising the database
    mydb = mysql.connector.connect(
        host="db",
        user="username",
        password="password",
    )
    mycursor = mydb.cursor()
    # first check if the database exists
    # if it exists return error
    mycursor.execute("SHOW DATABASES")
    databases = mycursor.fetchall()
    for db in databases:
        if db[0] == 'loadbalancer':
            message = '<ERROR> Database already initialized'
            return jsonify({'message': message, 'status': 'failure'}), 400
    
    mycursor.execute("CREATE DATABASE loadbalancer")
    mycursor.execute("USE loadbalancer")

    # Create the table for the load balancer
    mycursor.execute("CREATE TABLE ShardT (Stud_id_low INT PRIMARY KEY, Shard_id INT, Shard_size INT, valid_idx INT)")
    mycursor.execute("CREATE TABLE MapT (Shard_id INT, Server_id INT)")
    
    # Insert the shards into the ShardT table
    for shard in shards:
        # TODO: valid_idx
        mycursor.execute(f"INSERT INTO ShardT (Stud_id_low, Shard_id, Shard_size, valid_idx) VALUES ({shard['Stud_id_low']}, {shard['Shard_id']}, {shard['Shard_size']}, 0)")
    
    # Create locks and HashRing objects for each shard
    for shard in shards:
        shard_to_hrlock[shard['Shard_id']] = threading.Lock()
        shard_to_hr[shard['Shard_id']] = HashRing(hashtype = "sha256")

    response = add_servers(n, shard_mapping, mycursor)
    if response[1] != 200:
        return response
        
    mydb.commit()
    mycursor.close()
    mydb.close()
    message = 'Configured Database'
    return jsonify({'message': message, 'status': 'success'}), 200

'''
(/status, method=GET):This endpoint sends the database configurations upon request
Sample Response = 
{
    "N":3
    "schema":{"columns":["Stud_id","Stud_name","Stud_marks"],"dtypes":["Number","String","String"]}
    "shards":[{"Stud_id_low":0, "Shard_id": "sh1", "Shard_size":4096},
              {"Stud_id_low":4096, "Shard_id": "sh2", "Shard_size":4096},
              {"Stud_id_low":8192, "Shard_id": "sh3", "Shard_size":4096},]
    "servers":{"Server0":["sh1","sh2"],
               "Server1":["sh2","sh3"],
               "Server2":["sh1","sh3"]}
}
'''
@app.route('/status', methods=['GET'])
def status():
    mydb = mysql.connector.connect(
        host="db",
        user="username",
        password="password",
        database="loadbalancer"
    )
    mycursor = mydb.cursor()

    # Get the schema
    mycursor.execute("SELECT * FROM ShardT")
    shards = mycursor.fetchall()
    
    shards_list = []
    for shard in shards:
        shards_list.append({
            "Stud_id_low": shard[0],
            "Shard_id": shard[1],
            "Shard_size": shard[2]
        })
    
    mycursor.execute("SELECT * FROM MapT")
    shard_mapping = mycursor.fetchall()
    servers_dict = {}
    for shard in shard_mapping:
        if shard[1] in servers_dict:
            servers_dict[shard[1]].append(shard[0])
        else:
            servers_dict[shard[1]] = [shard[0]]
    
    servers = {}
    for server in servers_dict:
        # Here convert the internal server names to external server names
        for replica in replicas:
            if replica[1] == f'Server_{server}':
                servers[replica[0]] = servers_dict[server]
                break

    mycursor.close()
    mydb.close()
    return jsonify({'N': len(servers), 'schema': studT_schema, 'shards': shards_list, 'servers': servers}), 200

'''
(/add,method=POST): This  endpoint  adds  new  server  instances  in  the  load  balancer  to  scale  up  with increasing  client  numbers  in  the  system.  The  endpoint  expects  a  JSON  payload  that  mentions  the  number  of  newinstances, their server names, and the shard placements. An example request and response is below.
Payload Json= 
{
    "n" : 2,
    new_shards:[{"Stud_id_low":12288, "Shard_id": "sh5", "Shard_size":4096}]
    "servers" : {"Server4":["sh3","sh5"], /*new shards must be defined*/
                 "Server[5]":["sh2","sh5"]}
}
Response Json =
{
    "N":5,
    "message" : "Add Server:4 and Server:58127", /*server id is randomly set in case ofServer[5]*/
    "status" : "successful"
},
Response Code = 200
'''
@app.route('/add', methods=['POST'])
def add():
    content = request.get_json(force=True)
    n = content['n']
    new_shards = content['new_shards']
    shard_mapping = content['servers']

    # Sanity check
    if len(shard_mapping) != n:
        message = '<ERROR> Number of servers does not match the number of servers provided'
        return jsonify({'message': message, 'status': 'failure'}), 400
    
    # Sanity check
    for server in shard_mapping:
        if len(shard_mapping[server]) == 0:
            message = '<ERROR> No shards assigned to server'
            return jsonify({'message': message, 'status': 'failure'}), 400
    
    # Sanity check
    for shard in new_shards:
        if shard['Stud_id_low'] < 0:
            message = '<ERROR> Stud_id_low cannot be negative'
            return jsonify({'message': message, 'status': 'failure'}), 400
        if shard['Shard_size'] <= 0:
            message = '<ERROR> Shard_size cannot be non-positive'
            return jsonify({'message': message, 'status': 'failure'}), 400
    
    mydb = mysql.connector.connect(
        host="db",
        user="username",
        password="password",
        database="loadbalancer"
    )
    mycursor = mydb.cursor()

    # Insert the shards into the ShardT table
    for shard in new_shards:
        mycursor.execute(f"INSERT INTO ShardT (Stud_id_low, Shard_id, Shard_size, valid_idx) VALUES ({shard['Stud_id_low']}, {shard['Shard_id']}, {shard['Shard_size']}, 0)")
    
    for shard in new_shards:
        shard_to_hrlock[shard['Shard_id']] = threading.Lock()
        shard_to_hr[shard['Shard_id']] = HashRing(hashtype = "sha256")

    response = add_servers(n, shard_mapping, mycursor)
    if response[1] != 200:
        return response
    
    mydb.commit()
    mycursor.close()
    mydb.close()

    message = f'Add Servers: {", ".join(shard_mapping.keys())}'
    return jsonify({'N': len(replicas), 'message': message, 'status': 'successful'}), 200

'''
(/rm,method=DELETE): 
'''
@app.route('/rm', methods=['DELETE'])
def remove():
    # TODO: code
    content = request.get_json(force=True)
    n = content['n']
    hostnames = content['servers']
    if len(hostnames) > n:
        message = '<ERROR> Length of server list is more than removable instances'
        return jsonify({'message': message, 'status': 'failure'}), 400
    
    # Sanity check
    for hostname in hostnames:
        if hostname not in replicas:
            message = '<ERROR> Hostname does not exist'
            return jsonify({'message': message, 'status': 'failure'}), 400
        
    # Sanity check
    if n > len(replicas):
        message = '<ERROR> n is more than number of servers available'
        return jsonify({'message': message, 'status': 'failure'}), 400
    
    # First delete the named replicas
    # remove the docker container, remove the server from the hashring, remove the server from the replicas list, and remove the server from the MapT table
    replica_lock.acquire()
    new_replicas = []
    # for hostname in hostnames:
    for replica in replicas:
        if replica[0] in hostnames:
            hostname = replica[0]
            os.system(f'docker stop {replica[1]} && docker rm {replica[1]}')
            
            replicas.remove(replica)
            mydb = mysql.connector.connect(
                host="db",
                user="username",
                password="password",
                database="loadbalancer"
            )
            # Find the shard IDs that the server is responsible for
            shard_ids = []
            mycursor = mydb.cursor()
            mycursor.execute(f"SELECT Shard_id FROM MapT WHERE Server_id = {replica[1][7:]}")
            shard_ids = mycursor.fetchall()
            # Remove the server from the MapT table
            mycursor.execute(f"DELETE FROM MapT WHERE Server_id = {replica[1][7:]}")
            mydb.commit()
            mycursor.close()
            mydb.close()

            # Remove the server from hashrings of the shards
            for shard in shard_ids:
                shard_to_hrlock[shard].acquire()
                shard_to_hr[shard].remove_server(replica[1])
                shard_to_hrlock[shard].release()

            n -= 1
        else:
            new_replicas.append(replica)

    replicas = new_replicas
    


    # Then delete the unnamed replicas
    replicas_tobedeleted = replicas.copy()
    replica_lock.release()

    random.shuffle(replicas_tobedeleted)
    while len(replicas_tobedeleted) > n:
        replicas_tobedeleted.pop()

    replica_lock.acquire()
    for replica in replicas_tobedeleted:
        os.system(f'docker stop {replica[1]} && docker rm {replica[1]}')
        mydb = mysql.connector.connect(
            host="db",
            user="username",
            password="password",
            database="loadbalancer"
        )
        # Find the shard IDs that the server is responsible for
        shard_ids = []
        mycursor = mydb.cursor()
        mycursor.execute(f"SELECT Shard_id FROM MapT WHERE Server_id = {replica[1][7:]}")
        shard_ids = mycursor.fetchall()
        # Remove the server from the MapT table
        mycursor.execute(f"DELETE FROM MapT WHERE Server_id = {replica[1][7:]}")
        mydb.commit()
        mycursor.close()
        mydb.close()

        # Remove the server from hashrings of the shards
        for shard in shard_ids:
            shard_to_hrlock[shard].acquire()
            shard_to_hr[shard].remove_server(replica[1])
            shard_to_hrlock[shard].release()

    new_replicas = []
    for replica in replicas:
        if replica not in replicas_tobedeleted:
            new_replicas.append(replica)
    replicas = new_replicas

    replica_lock.release()
    deleted_replica_names = [replica[0] for replica in replicas_tobedeleted]
    deleted_replica_names += hostnames

    message = {
        'N': len(replicas),
        'servers': deleted_replica_names
    }

    return jsonify({'message': message, 'status': 'successful'}), 200
    

    
'''
(/read, method=POST):
'''
@app.route('/read', methods=['POST'])
def read():
    # TODO: code
    content = request.get_json(force=True)
    stud_id_low = content['Stud_id']['low']
    stud_id_high = content['Stud_id']['high']

    # Find the shards that contain the data
    mydb = mysql.connector.connect(
        host="db",
        user="username",
        password="password",
        database="loadbalancer"
    )
    mycursor = mydb.cursor()
    mycursor.execute(f"SELECT Shard_id FROM ShardT WHERE Stud_id_low <= {stud_id_high} AND Stud_id_low + Shard_size > {stud_id_low}")
    shards_list = mycursor.fetchall()
    mycursor.close()
    mydb.close()

    # For each shard, find a server using the hashring and forward the request to the server
    data = {}
    for shard in shards_list:
        shard_to_hrlock[shard].acquire()
        server = shard_to_hr[shard].get_server(random.randint(0, 999999))
        shard_to_hrlock[shard].release()
        if server != None:
            try:
                reply = requests.post(f'http://{server}:{serverport}/read', json = {
                    "shard": shard,
                    "Stud_id": {"low": stud_id_low, "high": stud_id_high}
                })
                data[shard] = reply.json()
            except requests.exceptions.ConnectionError:
                message = '<ERROR> Server unavailable'
                data[shard] = {'message': message, 'status': 'failure'}
        else:
            message = '<ERROR> Server unavailable'
            data[shard] = {'message': message, 'status': 'failure'}

    # merge the responses from the shards
    merged_data = []
    for shard in data:
        if data[shard]['status'] == 'success':
            merged_data += data[shard]['data']

    response = {
        "shards_queried": shards_list,
        "data": merged_data,
        "status": "success"
    }
    return jsonify(response), 200



'''
(/<path>,method=GET): This endpoint is the main endpoint that forwards the request to the backend server.
'''
@app.route('/<path>', methods=['GET'])
def forward_request(path):
    # Generate a random 6 digit request ID and get hostname of a replica from the hashring
    hrlock.acquire()
    server = hr.get_server(random.randint(0, 999999))
    hrlock.release()
    if server != None:
        # Forward the request and return the response
        try:
            reply = requests.get(f'http://{server}:{serverport}/{path}')
            return reply.json(), reply.status_code
        except requests.exceptions.ConnectionError:
            # Replica is down
            hrlock.acquire()
            hr.remove_server(server)
            hrlock.release()
            message = '<ERROR> Server unavailable'
            return jsonify({'message': message, 'status': 'failure'}), 400
    else:
        message = '<ERROR> Server unavailable'
        return jsonify({'message': message, 'status': 'failure'}), 400

def manage_replicas():
    '''
    Entrypoint for thread that checks the replicas for heartbeats every 10 seconds.
    '''
    while True:
        replica_lock.acquire()
        for replica in replicas:
            serverdown = False
            try:
                reply = requests.get(f'http://{replica[1]}:{serverport}/heartbeat')
            except requests.exceptions.ConnectionError:
                # Replica is down
                print(f'Replica {replica[1]} is down')
                # Ensure that the replica container is stopped and removed
                os.system(f'docker stop {replica[1]} && docker rm {replica[1]}')
                # Replace the replica with a new replica
                serverid = replica[1][7:]
                # We use the same name instead of generating a new name to keep the naming consistent
                os.system(f'docker run --name {replica[1]} --network mynet --network-alias {replica[1]} -e SERVER_ID={serverid} -d serverim:latest')
                hrlock.acquire()
                hr.remove_server(replica[1])
                hr.add_server(replica[1])
                hrlock.release()
            else:
                hrlock.acquire()
                if reply.status_code != 200 or replica[1] not in hr.name_to_serverid.keys():
                    # Replica is not heartbeating, so it is assumed to be down
                    print(f'Replica {replica[1]} is not responding to heartbeat, killing it')
                    # Ensure that the replica container is stopped and removed
                    os.system(f'docker stop {replica[1]} && docker rm {replica[1]}')
                    # Replace the replica with a new replica
                    serverid = replica[1][7:]
                    os.system(f'docker run --name {replica[1]} --network mynet --network-alias {replica[1]} -e SERVER_ID={serverid} -d serverim:latest')
                    hr.remove_server(replica[1])
                    hr.add_server(replica[1])
                hrlock.release()
        replica_lock.release()
        # Sleep for 10 seconds
        time.sleep(10)
    
if __name__ == '__main__':
    serverport = 5000

    # Replicas is a list of lists. Each list has two entries: the External Name (user-specified or randomly generated) and the Container Name
    # The Container Name is the name of the container, and is the same as the hostname of the container. It is always of the form Server_<serverid>
    replicas = []
    # Bookkeeping for server IDs
    server_ids = set()
    next_server_id = 1

    num_servers = 0
    studT_schema = ""

    # Setting up and spawning the thread that manages the replicas
    thread = threading.Thread(target=manage_replicas)
    thread.start()
    
    # Start the server
    app.run(host='0.0.0.0', port=5000, debug=False)