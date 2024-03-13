from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import mysql.connector

app = Flask(__name__)
CORS(app)

# For testing purposes, you can set the server ID as an environment variable while running the container instance of the server.
os.environ['SERVER_ID'] = '1231'

# Connect to the MySQL database
mydb = mysql.connector.connect(
    host="localhost", 
    user="root",
    password="abc")
mycursor = mydb.cursor(dictionary=True)
# Create a database to store the shards
mycursor.execute("CREATE DATABASE shards")
mycursor.execute("USE shards")


'''
(/config,method=POST): This endpoint initializes the shard tables in the server database after the container
is loaded. The shards are configured according to the request payload.
Sample Payload Json:
{
    "schema": {"columns":["Stud_id","Stud_name","Stud_marks"],
                "dtypes": ["Number","String","String"]},
    "shards": ["sh1","sh2"]
}
Response Json:
{
    "message" : "Server0:sh1, Server0:sh2 configured",
    "status" : "success"
},
Response Code = 200
''' 
@app.route('/config', methods=['POST'])
def config():
    data = request.json
    shards = data['shards']
    schema = data['schema']
    columns = schema['columns']
    dtypes = schema['dtypes']
    server_id = os.environ['SERVER_ID']
    for i in range(len(dtypes)):
        if dtypes[i] == 'Number':
            dtypes[i] = 'INT'
        elif dtypes[i] == 'String':
            dtypes[i] = 'VARCHAR(255)'
    for shard in shards:
        # Create a table for each shard
        # The table name is the shard name
        # Assume that the first colummn is the primary key
        mycursor.execute("CREATE TABLE {} ({} {} PRIMARY KEY)".format(shard, columns[0], dtypes[0]))
        for i in range(1, len(columns)):
            mycursor.execute("ALTER TABLE {} ADD COLUMN {} {}".format(shard, columns[i], dtypes[i]))
    mydb.commit()
    message = ''
    for i in range(len(shards)):
        message += 'Server{}:{}'.format(server_id, shards[i])
        if i != len(shards) - 1:
            message += ', '
    message += ' configured'
    return jsonify({'message': message, 'status': 'success'}), 200




'''
(/heartbeat,method=GET): This endpoint is used for health checks of the server instance.
No request payload is required and it returns an empty response with a 200 status code.
'''
@app.route('/heartbeat', methods=['GET'])
def heartbeat():
    return '', 200

'''
(/copy,method=POST): This endpoint returns all the data from the shard table in the server database.
Sample Payload Json:
{
    "shards":["sh1","sh2"]
}
Response Json:
{
    "sh1" : [{"Stud_id":1232,"Stud_name":ABC,"Stud_marks":25},
            {"Stud_id":1234,"Stud_name":DEF,"Stud_marks":28},
            ....],
    "sh2" : [{"Stud_id":2255,"Stud_name":GHI,"Stud_marks":27},
            {"Stud_id":2535,"Stud_name":JKL,"Stud_marks":23},
            ....],
    "status" : "success"
},
Response Code = 200
'''
@app.route('/copy', methods=['POST'])
def copy():
    data = request.json
    shards = data['shards']
    response = {}
    for shard in shards:
        mycursor.execute("SELECT * FROM {}".format(shard))
        response[shard] = mycursor.fetchall()
    response['status'] = 'success'
    return jsonify(response), 200

'''
(/read,method=POST): This endpoint returns the data from a shard. It expects a range of Stud_ids and the shard name.
Sample Payload Json:
{
    "shard":"sh2",
    "Stud_id": {"low":2235, "high":2555}
}
Response Json:
{
    "data" : [{"Stud_id":2535,"Stud_name":JKL,"Stud_marks":23},
            {"Stud_id":2536,"Stud_name":MNO,"Stud_marks":22},
            .....,
            {"Stud_id":2554,"Stud_name":XYZ,"Stud_marks":25},
            {"Stud_id":2255,"Stud_name":GHI,"Stud_marks":27}],
    "status" : "success"
},
Response Code = 200
'''
@app.route('/read', methods=['POST'])
def read():
    data = request.json
    shard = data['shard']
    low = data['Stud_id']['low']
    high = data['Stud_id']['high']
    mycursor.execute("SELECT * FROM {} WHERE Stud_id BETWEEN {} AND {}".format(shard, low, high))
    response = mycursor.fetchall()
    return jsonify({'data': response, 'status': 'success'}), 200


'''
(/write,method=POST): This endpoint writes the data to the shard table in the server database. It expects multiple entries and updates a curr_idx with the number of entries.
Sample Payload Json:
{
    "shard":"sh2",
    "curr_idx": 507
    "data": [{"Stud_id":2255,"Stud_name":GHI,"Stud_marks":27}, ...] /* 5 entries */
}
Response Json:
{
    "message": "Data entries added",
    "current_idx": 512, /* 5 entries added */
    "status" : "success"
},
Response Code = 200
'''
@app.route('/write', methods=['POST'])
def write():
    data = request.json
    shard = data['shard']
    curr_idx = data['curr_idx']
    entries = data['data']
    for entry in entries:
        columns = ', '.join(entry.keys())
        values = ', '.join(['"{}"'.format(str(x)) for x in entry.values()])
        mycursor.execute("INSERT INTO {} ({}) VALUES ({})".format(shard, columns, values))
    mydb.commit()
    return jsonify({'message': 'Data entries added', 'current_idx': curr_idx + len(entries), 'status': 'success'}), 200


'''
(/update,method=POST): This endpoint updates the data in the shard table in the server database. It expects a Stud_id, shard name and the updated data.
Sample Payload Json:
{
    "shard":"sh2",
    "Stud_id":2255,
    "data": {"Stud_id":2255,"Stud_name":GHI,"Stud_marks":28} /* see marks got updated */
}
Response Json:
{
    "message": "Data entry for Stud_id:2255 updated",
    "status" : "success"
},
Response Code = 200
'''
@app.route('/update', methods=['POST'])
def update():
    data = request.json
    shard = data['shard']
    Stud_id = data['Stud_id']
    entry = data['data']
    update = ', '.join(['{} = "{}"'.format(k, v) for k, v in entry.items()])
    mycursor.execute("UPDATE {} SET {} WHERE Stud_id = {}".format(shard, update, Stud_id))
    mydb.commit()
    return jsonify({'message': 'Data entry for Stud_id:{} updated'.format(Stud_id), 'status': 'success'}), 200


'''
(/delete,method=POST): This endpoint deletes the data from the shard table in the server database. It expects a Stud_id and the shard name.
Sample Payload Json:
{
    "shard":"sh2",
    "Stud_id":2255
}
Response Json:
{
    "message": "Data entry with Stud_id:2255 removed",
    "status" : "success"
},
Response Code = 200
'''
@app.route('/delete', methods=['POST'])
def delete():
    data = request.json
    shard = data['shard']
    Stud_id = data['Stud_id']
    mycursor.execute("DELETE FROM {} WHERE Stud_id = {}".format(shard, Stud_id))
    mydb.commit()
    return jsonify({'message': 'Data entry with Stud_id:{} removed'.format(Stud_id), 'status': 'success'}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
