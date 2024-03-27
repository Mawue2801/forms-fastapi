from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Record(BaseModel):
    parameter1: str
    parameter2: str
    parameter3: str

@app.post("/add_record/")
async def add_record(record: Record):
    # Here you can process the received data, for example, save it to a database
    # For simplicity, let's just print the received data and return it along with the success message
    print("Received Record:")
    print(record)
    return {"message": "Record added successfully", "record": record.dict()}