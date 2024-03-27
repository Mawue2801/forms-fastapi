from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import os
import asyncpg
import json
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

class Record(BaseModel):
    id: int
    event_name: str
    parameters: dict

# Database Connection Pool
async def create_db_pool():
    return await asyncpg.create_pool(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        min_size=1,
        max_size=5
    )

# Endpoint to create the record
@app.post("/records/")
async def create_record(record: Record):
    async with app.state.db_pool.acquire() as connection:
        try:
            parameters_json = json.dumps(record.parameters)
            record_id = await connection.fetchval("INSERT INTO records (event_name, parameters) VALUES ($1, $2) RETURNING id",
                                                  record.event_name, parameters_json)
            return {"id": record_id, **record.dict()}
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to create record")

# Endpoint to read all records for a given event name
@app.get("/records/{event_name}/")
async def read_records_by_event_name(event_name: str):
    async with app.state.db_pool.acquire() as connection:
        try:
            records = await connection.fetch(
                "SELECT id, parameters FROM records WHERE event_name = $1", event_name)
            return [{"id": record['id'], **json.loads(record['parameters'])} for record in records]
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to read records")

# Endpoint to read one record given its id
@app.get("/record/{record_id}/")
async def read_record(record_id: int):
    async with app.state.db_pool.acquire() as connection:
        try:
            record = await connection.fetchrow(
                "SELECT event_name, parameters FROM records WHERE id = $1", record_id)
            if record:
                return {"id": record_id, "event_name": record['event_name'], **json.loads(record['parameters'])}
            else:
                raise HTTPException(status_code=404, detail="Record not found")
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to read record")

# Endpoint to read all records
@app.get("/records/")
async def read_records():
    async with app.state.db_pool.acquire() as connection:
        try:
            records = await connection.fetch("SELECT id, event_name, parameters FROM records")
            return [{"id": record['id'], "event_name": record['event_name'], **json.loads(record['parameters'])}
                    for record in records]
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to read records")

# Endpoint to update a record
@app.put("/record/{record_id}/")
async def update_record(record_id: int, record: Record):
    async with app.state.db_pool.acquire() as connection:
        try:
            parameters_json = json.dumps(record.parameters)
            await connection.execute("UPDATE records SET event_name = $1, parameters = $2 WHERE id = $3",
                                     record.event_name, parameters_json, record_id)
            return {"id": record_id, **record.dict()}
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to update record")

# Endpoint to delete a record
@app.delete("/record/{record_id}/")
async def delete_record(record_id: int):
    async with app.state.db_pool.acquire() as connection:
        try:
            await connection.execute("DELETE FROM records WHERE id = $1", record_id)
            return {"message": "Record deleted successfully"}
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to delete record")

# Register the database connection pool creation as a startup event handler
app.add_event_handler("startup", create_db_pool)