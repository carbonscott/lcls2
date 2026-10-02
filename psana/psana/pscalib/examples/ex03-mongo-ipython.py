
"""Example: connect to the MongoDB server ``psanaphi105:27017``, open DB ``calib-cxi12345`` with GridFS and print its collection and first document.

All statements run at import time. It uses ``client.database_names()`` and ``db.collection_names()``,
which newer pymongo versions no longer provide.
"""
import gridfs
from pymongo import MongoClient

#client = MongoClient('localhost', 27017)
client = MongoClient('psanaphi105', 27017) #, username=uname, password=pwd)
db = client['calib-cxi12345']
fs = gridfs.GridFS(db)

col = db['cxi12345']
docs = col.find()
doc = docs[0]

print('client.database_names(): ', client.database_names())
print('db.collection_names()  : ', db.collection_names(False))

print('==== fs :\n', fs)
print('==== col :\n', col)
print('==== docs :\n', docs)
print('==== doc :\n', doc)
print('==== vars(col) :\n', vars(col))
