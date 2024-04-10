# Assignment-2: Implementing a Scalable Database with Sharding

## Table of Contents

- [Assignment-2: Implementing a Scalable Database with Sharding](#assignment-2-customizable-load-balancer)
  - [Table of Contents](#table-of-contents)
  - [Docker and Docker Compose](#docker-and-docker-compose)
    - [Installation](#installation)
  - [Instructions](#instructions)
  - [Server](#server)
  - [HashRing](#hashring)
    - [Usage](#usage)
    - [Design Choices](#design-choices)
  - [Load Balancer](#load-balancer)
  - [Database Tables](#database-tables)
  - [Analysis](#analysis)
  - [Client](#client)

## Docker and Docker Compose

The docker containers are based on the `ubuntu:20.04` image which is a full-fledged OS. This is to ensure that the containers are self-sufficient and thus do not require any external dependencies or a particular OS to run. The only requirements to run the containers are `docker` and `docker-compose`.  

### Installation
You can get the installation instructions for docker and docker-compose from the following links:
* [Docker](https://docs.docker.com/engine/install/)
* [Docker Compose](https://docs.docker.com/compose/install/)

## Instructions

The Makefile lists all the commands required for deploying the load balancer network as well as for deploying the client.

* `make all`: build the server image deploy the docker compose
* `make clean`: stops and removes the running servers, brings the compose down and removes the load balancer and server images

`curl` command can be used to send requests to the load balancer from the host machine in the following format:

```bash
curl --request <request-type> [-d @payload.json] http://localhost:5000/<endpoint>
```

Here the `request-type` can be `GET, POST, or DELETE` depending on the `endpoint`. For the ease of sending payload data in case of /add and /rm, a separate `payload.json` file can be used.

## Server

The servers have a hostname which is what is received by the client and can be set by the client. However, the container name of the server follows the format `Server_{SERVER_ID}`. This container name is used in all the internal workings and can not be set by the client.

The server accepts HTTP requests on port 5000 in the endpoints:

- **/config (method = POST):**
  This endpoint initializes the shard tables in the server database after the container is loaded. The shards are configured according to the request payload. It returns a success message and a status code of 200.

- **/heartbeat (method = GET):**
  This endpoint is used for health checks of the server instance. It doesn't require a request payload and returns an empty response with a 200 status code.

- **/copy (method = POST):**
  This endpoint returns all the data from the shard table in the server database. It requires a payload with the shard names and returns the data from the shards along with a success status.

- **/read (method = POST):**
  This endpoint returns the data from a shard. It expects a range of Stud_ids and the shard name in the request payload. It returns the data within the range from the specified shard.

- **/write (method = POST):**
  This endpoint writes the data to the shard table in the server database. It expects multiple entries and updates a curr_idx with the number of entries. It returns a success message, the updated curr_idx, and a status code of 200.

- **/update (method = POST):**
  This endpoint updates the data in the shard table in the server database. It expects a Stud_id, shard name, and the updated data in the request payload. It returns a success message and a status code of 200.

- **/delete (method = POST):**
  This endpoint deletes the data from the shard table in the server database. It expects a Stud_id and the shard name in the request payload. It returns a success message and a status code of 200.

## HashRing

The `HashRing` class implements a distributed hash ring using consistent hashing. It provides a way to map keys or request IDs to servers in a distributed system. Consistent hashing is a technique that allows for dynamic scaling and load balancing in distributed systems.

### Usage

To use the `HashRing` class, follow these steps:

1. **Initialization**: Create an instance of the `HashRing` class by providing the number of virtual nodes, size of the ring (`M`) and a hash function (`H`) as parameters.
2. **Adding Servers**: Add servers to the hash ring using the `add_server` method. Each server is identified by a unique server ID. The server is hashed and placed on the ring at multiple points corresponding to its virtual nodes.
3. **Mapping Requests**: Map a request ID to a server using the `get_server` method. This method takes a request ID as an argument and returns the name of the server to which the request is mapped. If the initial position of the request ID on the hash ring is already occupied by another server, linear probing is used to find the next available position.
4. **Removing Servers**: Remove a server from the hash ring using the `remove_server` method. This method takes a server ID as an argument and removes all the virtual nodes of that server from the hash ring.

### Design Choices

The `HashRing` class makes the following design choices:

- **Consistent Hashing**: Consistent hashing is used to distribute keys or request IDs across the servers in a balanced manner. This ensures that the load is evenly distributed and allows for easy addition or removal of servers without causing significant remapping of keys.
- **Virtual Nodes**: The hash ring uses virtual nodes to improve the distribution of keys. Each server is represented by multiple virtual nodes on the hash ring, which helps to balance the load even further.
- **Linear Probing**: In the `get_server` method, if the initial position of the request ID on the hash ring is already occupied by another server, linear probing is used to find the next available position. This ensures that the request is always mapped to a server, even if collisions occur.
- **Null Return**: If no server is found for a given request ID, the `get_server` method returns `None`. Similarly, if a server to be removed does not exist in the hash ring, the `remove_server` method does nothing.

Please refer to the code documentation for more details on the implementation.

## Load Balancer

The load balancer uses the HashRing data structure to manage a set of N web server containers. The load balancer is run as a separate container which then spawns the server containers. The load balancer and the servers are run on the same network so that the load balancer can communicate with the servers. Only port 5000 is exposed for the load balancer to receive requests. The servers are not exposed to the host machine.  

The load balancer is a multi-threaded process. The main thread handles all the requests to the various endpoints (which have been described below). The secondary thread is responsible for maintaining the number of servers. This thread periodically (set to 10 seconds) requests heartbeat from each server (maintained in a global list). If it finds a non-responsive server, it will first remove the container from the docker and then spawn another container with the same hostname and container name as the deleted server.

The load balancer endpoints are exposed at port 5000. We have exposed the following endpoints:

- **/init (method = POST):**
  This endpoint initializes the distributed database across different shards and replicas in the server containers. t expects a JSON payload containing information about the number of servers (N), the database schema (schema), the shards (shards), and the servers with their assigned shards (servers).

- **/status (method = GET):**
  This endpoint sends the database configurations upon request.It returns a JSON object containing information about the number of servers (N), the database schema (schema), the shards (shards), and the servers with their assigned shards (servers).

- **/add (method = POST):**
  This endpoint adds new server instances to the load balancer to scale up with increasing client numbers in the system. It expects a JSON payload specifying the number of new instances (n), the new shards (new_shards), and the servers with their assigned shards (servers).
  
- **/rm (method = DELETE):**
  This endpoint removes server instances from the load balancer. It expects a JSON payload specifying the number of instances to remove (n) and the hostnames of the servers to remove (servers).
  
- **/read (method = POST):**
  This endpoint reads data from the distributed database based on the provided range of student IDs. It expects a JSON payload containing the range of student IDs (Stud_id.low and Stud_id.high).
  
- **/write (method = POST):**
  This endpoint writes data to the distributed database. It expects a JSON payload containing the data to be written, including student ID, name, and marks.

- **/update (method = PUT):**
  This endpoint updates the data of a specific student in the distributed database. It expects a JSON payload containing the student ID and the updated data (name and marks).
  
- **/delete (method = DELETE):**
  This endpoint deletes the data of a specific student from the distributed database. It expects a JSON payload containing the student ID.

## Database Tables
In the system architecture, two data tables are utilized for managing the distribution of shards across server containers: ShardT and MapT. Below are descriptions of these tables and instructions on how to access them:

### ShardT Table
The ShardT table is responsible for storing information about shards in the distributed database. It contains the following columns:

- **Stud id low:** The lower bound of the range of student IDs that the shard represents.
- **Shard id:** Unique identifier for each shard.
- **Shard size:** Number of records stored in the shard.
- **Valid idx:** Index indicating the validity status of the shard.

Accessing ShardT Table:
To access the ShardT table, you can query the database or data storage system used by the load balancer. The specific method for accessing this table depends on the implementation details of the system.

### MapT Table
The MapT table maintains the mapping between shard IDs and server IDs, indicating which server container is responsible for each shard. It consists of the following columns:

- **Shard id:**  The identifier of the shard.
- **Server id:** The identifier of the server container responsible for storing the shard.

Accessing MapT Table:
Similar to the ShardT table, accessing the MapT table involves querying the database or data storage system utilized by the load balancer. You can retrieve the mapping information by querying this table using appropriate SQL or NoSQL queries, depending on the database technology used.
  
## Analysis

We have written scripts to run the required tests on the code, and the results along with the code can be found in the `analysis` folder. The tests are described below:
1. **Test A-1: Default Configuration Performance**: This test measures the read and write speeds for 10000 writes and 10000 reads in the default configuration specified in Task 2.
2. **Test A-2: Increase Shard Replicas**: This test increments the number of servers from 2 to 7 and sends 10000 reads and writes to the load balancer. We report the decrease in write speed for 10000 writes and the increase in read speed for 10000 reads.
3. **Test A-3: Increase Number of Servers and Shards**: We increase the number of servers to 10 by adding new servers and increase the number of shards to 6 with shard replicas set to 8. We then report the increase in write speed for 10000 writes and read speed for 10000 reads.
4. **Test A-4: Endpoint Functionality Check**: We verify the correctness of all endpoints. We then drop a server container and observe the load balancer's behavior in spawning a new container and copying shard entries from other replicas.
