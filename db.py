import os
import pymongo
from dotenv import load_dotenv
load_dotenv()
MONGODB_URI = os.environ.get("MONGODB_URI")
if not MONGODB_URI:
    raise ValueError("MONGODB_URI environment variable is not set")

client = pymongo.MongoClient(MONGODB_URI)
db = client["thirty_days_of_python"]