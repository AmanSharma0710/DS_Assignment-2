from hashring import HashRing

hashring = HashRing()

hashring.add_server("smd")
hashring.add_server("smd1")
hashring.add_server("smd2")
hashring.print_serveralloc()
hashring.remove_server("smd")
hashring.print_serveralloc()
hashring.remove_server("smd1")
hashring.print_serveralloc()
for i in range(10):
    print(hashring.get_server(i))