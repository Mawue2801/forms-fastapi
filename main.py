from fastapi import FastAPI, HTTPException, Depends, Request, Form, responses, Query, Response, UploadFile, File
from fastapi.responses import RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse, FileResponse
from starlette.requests import Request
from pydantic import BaseModel
import os
import asyncpg
import json
from dotenv import load_dotenv
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import Optional
import jwt
from datetime import datetime, timedelta
from fastapi.staticfiles import StaticFiles
import csv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Mount the static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Secret key for signing JWT tokens
SECRET_KEY = os.getenv("SECRET_KEY")

# Token expiration time
ACCESS_TOKEN_EXPIRE_MINUTES = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")

BASE_URL = os.getenv("BASE_URL")

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

EVENT_NAME = os.getenv("EVENT_NAME")
SPECIFIED_COLUMNS = os.getenv("SPECIFIED_COLUMNS")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Sample event staff model
class EventStaff(BaseModel):
    email: str
    password: str

class Record(BaseModel):
    event_name: str
    parameters: dict

# Database Connection Pool
async def create_db_pool():
    db_pool = await asyncpg.create_pool(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        min_size=1,
        max_size=5
    )
    return db_pool

# Generate password hash
def get_password_hash(password):
    return pwd_context.hash(password)

# Verify password
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Token creation
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")
    return encoded_jwt

# Authentication middleware
async def get_current_user(token: str = Depends(create_access_token)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return email

@app.get("/", include_in_schema=False)
async def index() -> responses.RedirectResponse:
    return responses.RedirectResponse(url="/docs")

# Create event staff endpoint
@app.post("/event-staff/", response_model=EventStaff)
async def create_event_staff(staff: EventStaff, event_name: str = EVENT_NAME, specified_columns: str = SPECIFIED_COLUMNS, db_pool=Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            # Hash the password
            hashed_password = get_password_hash(staff.password)
            
            # Construct the SQL query with parameterized values
            query = f"""
                INSERT INTO event_staff (email, hashed_password, event_name, specified_columns)
                VALUES ($1, $2, $3, $4)
            """
            
            # Execute the SQL query with actual values
            await connection.execute(
                query,
                staff.email,
                hashed_password,
                event_name,
                specified_columns
            )
            
            return staff
        except asyncpg.exceptions.UniqueViolationError:
            raise HTTPException(status_code=400, detail="Email already registered")
        except Exception as e:
            raise HTTPException(status_code=500, detail="Failed to create event staff")
    
# Endpoint to render the login page
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# Endpoint to handle login form submission
@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), db_pool = Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        # Query the database to check if the event_staff exists and the password is correct
        event_staff = await connection.fetchrow(
            "SELECT id, email, hashed_password, event_name, specified_columns FROM event_staff WHERE email = $1", email)
        if event_staff is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # Check if the password matches
        if not verify_password(password, event_staff['hashed_password']):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # If the credentials are valid, create a JWT token and return it to the client
        access_token_expires = timedelta(minutes=int(ACCESS_TOKEN_EXPIRE_MINUTES))
        access_token = create_access_token(data={"sub": email}, expires_delta=access_token_expires)
        # return {"access_token": access_token, "token_type": "bearer"}
        # Redirect the user to the desired URL after successful login
        redirect_url = f"{BASE_URL}/records/{event_staff['event_name']}/?parameters={event_staff['specified_columns']}"
        return RedirectResponse(url=redirect_url, headers={"Authorization": f"Bearer {access_token}"})

# Protected endpoint example
@app.get("/protected/")
async def protected_route(current_user: str = Depends(get_current_user)):
    return {"message": f"Welcome {current_user}"}

# Logout endpoint (just for demonstration, as JWT tokens are stateless)
@app.post("/event-staff/logout/")
async def event_staff_logout():
    return RedirectResponse(url="/login")

# Update event staff password endpoint
@app.put("/event-staff/me/password/")
async def update_staff_password(new_password: str, current_user: str = Depends(get_current_user), db_pool = Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            hashed_password = get_password_hash(new_password)
            await connection.execute(
                "UPDATE event_staff SET hashed_password = $1 WHERE email = $2",
                hashed_password, current_user
            )
            return {"message": "Password updated successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail="Failed to update password")

# Delete event staff account endpoint
@app.delete("/event-staff/me/")
async def delete_event_staff_account(current_user: str = Depends(get_current_user), db_pool = Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            await connection.execute(
                "DELETE FROM event_staff WHERE email = $1",
                current_user
            )
            return {"message": "Event staff account deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail="Failed to delete event staff account")
        
# Endpoint to update the simple_code column
@app.put("/update_codes/")
async def update_codes(db_pool=Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            # Update simple_code column based on event_name and id
            await connection.execute('''
                UPDATE records
                SET code = event_name || '-' || LPAD(id::TEXT, 4, '0')
            ''')

            return {"message": "Codes updated successfully"}

        except asyncpg.PostgresError as e:
            raise HTTPException(status_code=500, detail=f"Error updating codes: {e}")
        
# Endpoint to create CSV file for a specified column
@app.get("/create_csv/")
async def create_csv(column: str = Query(...), db_pool=Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            # Fetch data for the specified column from the records table
            records = await connection.fetch("SELECT {} FROM records".format(column))
            if not records:
                raise HTTPException(status_code=404, detail="No records found")

            # Define directory to save CSV file
            directory = "files"
            if not os.path.exists(directory):
                os.makedirs(directory)

            # Define CSV file path
            csv_file_path = os.path.join(directory, f"data.csv")

            # Write data to CSV file
            with open(csv_file_path, mode='w', newline='') as file:
                writer = csv.writer(file)
                # writer.writerow([column])  # Write column header
                for record in records:
                    writer.writerow([record[column]])

            return {"message": f"CSV file created successfully at: {csv_file_path}"}

        except asyncpg.PostgresError as e:
            raise HTTPException(status_code=500, detail=f"Error fetching data: {e}")
        
# Endpoint to download the CSV file
@app.get("/download_csv/")
async def download_csv(response: Response):
    file_path = "files/data.csv"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="CSV file not found")

    return FileResponse(file_path, media_type='text/csv', filename="data.csv")

# Function to send email
async def send_email(subject, body, to_email, attachment_data, attachment_filename):
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587

    # Create the message
    message = MIMEMultipart()
    message['From'] = SENDER_EMAIL
    message['To'] = to_email
    message['Subject'] = subject

    # Attach the body of the email
    message.attach(MIMEText(body, 'plain'))

    # Attach the file
    attachment = MIMEApplication(attachment_data)
    attachment.add_header('Content-Disposition', 'attachment', filename=attachment_filename)
    message.attach(attachment)

    try:
        # Connect to the SMTP server
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            # Start the TLS connection
            server.starttls()

            # Login to your Gmail account
            server.login(SENDER_EMAIL, SENDER_PASSWORD)

            # Send the email
            server.sendmail(SENDER_EMAIL, to_email, message.as_string())
        
        # print("Email sent successfully!")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending email: {e}")

# Endpoint to upload CSV file and send via email
@app.post("/upload_csv/")
async def upload_csv(file: UploadFile = File(...)):
    try:
        # Read the file content into memory
        file_content = await file.read()

        # Send email with attachment
        await send_email(subject="CSV File Uploaded",
                         body=f"CSV file {file.filename} uploaded.",
                         to_email=RECIPIENT_EMAIL,
                         attachment_data=file_content,
                         attachment_filename=file.filename)

        return {"message": f"File '{file.filename}' uploaded successfully and sent via email."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading file and sending email: {e}")
    
# Endpoint to create the record
@app.post("/records/")
async def create_record(record: Record, db_pool = Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            parameters_json = json.dumps(record.parameters)
            record_id = await connection.fetchval("INSERT INTO records (event_name, parameters) VALUES ($1, $2) RETURNING id",
                                                  record.event_name, parameters_json)
            return {"id": record_id, **record.dict()}
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to create record")

@app.post("/records/{event_name}/", response_class=HTMLResponse)
async def read_records_by_event_name(request: Request, event_name: str, parameters: str = None, db_pool=Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            # Parse the parameters query parameter into a list
            if parameters:
                parameters_list = parameters.split(',')
                parameters_keys = set(parameters_list)  # Initialize parameters_keys with parameters_list
            else:
                parameters_list = None
                parameters_keys = set()

            # Fetch records from the database
            records = await connection.fetch(
                "SELECT code, event_name, parameters, signed_in, signed_out FROM records WHERE event_name = $1", event_name)

            # Convert each record to a dictionary and parse the 'parameters' field
            parsed_records = []
            for record in records:
                record_dict = dict(record)
                record_dict['parameters'] = json.loads(record['parameters'])
                parsed_records.append(record_dict)
                parameters_keys.update(record_dict['parameters'].keys())

            # print(parsed_records)

            # Filter parameters_keys based on the specified parameters_list
            if parameters_list:
                parameters_keys = [param for param in parameters_list if param in parameters_keys]

            # Render the template with the data
            return templates.TemplateResponse("records_template.html", {"request": request, "event_name": event_name, "records": parsed_records, "parameters_keys": parameters_keys, "parameters_list": parameters_list})
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to read records")

# Endpoint to read one record given its code
@app.get("/record/{code}/")
async def read_record(code: str, db_pool=Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            record = await connection.fetchrow(
                "SELECT event_name, parameters, code, created_at, signed_in, signed_out FROM records WHERE code = $1", code)
            if record:
                return {"code": code, "event_name": record['event_name'], "created_at": record['created_at'], "signed_in": record['signed_in'], "signed_out": record['signed_out'], **json.loads(record['parameters'])}
            else:
                raise HTTPException(status_code=404, detail="Record not found")
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to read record")

# Endpoint to read all records
@app.get("/records/")
async def read_records(db_pool = Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            records = await connection.fetch("SELECT id, event_name, parameters, code, created_at, signed_in, signed_out FROM records")
            return [{"id": record['id'], "event_name": record['event_name'], "created_at": record['created_at'], "code": record['code'], "signed_in": record['signed_in'], "signed_out": record['signed_out'], **json.loads(record['parameters'])}
                    for record in records]
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to read records")

# Endpoint to update a record
@app.put("/record/{code}/")
async def update_record(code: str, record: Record, signed_in: Optional[bool] = None, signed_out: Optional[bool] = None, db_pool=Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            parameters_json = json.dumps(record.parameters)
            # Modify the SQL query to update all columns based on the code
            await connection.execute(
                "UPDATE records SET event_name = $1, parameters = $2, signed_in = $3, signed_out = $4 WHERE code = $5",
                record.event_name, parameters_json, signed_in, signed_out, code)
            return {"code": code, **record.dict()}
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to update record")
        
# New endpoint to update signed_in or signed_out boolean columns
@app.put("/record/{code}/update_status/")
async def update_status(code: str, column: str, status: bool, db_pool=Depends(create_db_pool)):
    # Validate the column name
    if column not in ["signed_in", "signed_out"]:
        raise HTTPException(status_code=400, detail="Invalid column name")

    async with db_pool.acquire() as connection:
        try:
            # Construct the SQL query with placeholders
            query = "UPDATE records SET {} = $1 WHERE code = $2".format(column)
            await connection.execute(query, status, code)
            return {"message": "{} updated successfully for record {}".format(column, code)}
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail="Failed to update column")

# Endpoint to delete a record
@app.delete("/record/{code}/")
async def delete_record(code: str, db_pool=Depends(create_db_pool)):
    async with db_pool.acquire() as connection:
        try:
            # Check if the record exists before deleting it
            existing_record = await connection.fetchval(
                "SELECT 1 FROM records WHERE code = $1", code)
            if existing_record is not None:
                await connection.execute("DELETE FROM records WHERE code = $1", code)
                return {"message": "Record deleted successfully"}
            else:
                raise HTTPException(status_code=404, detail="Record not found")
        except Exception as e:
            print("Error:", e)
            raise HTTPException(status_code=500, detail=f"Failed to delete record")

# Register the database connection pool creation as a startup event handler
app.add_event_handler("startup", create_db_pool)

# Endpoint to read all records for a given event name
# @app.get("/records/{event_name}/")
# async def read_records_by_event_name(event_name: str, db_pool = Depends(create_db_pool)):
#     async with db_pool.acquire() as connection:
#         try:
#             records = await connection.fetch(
#                 "SELECT id, parameters, code, created_at, signed_in, signed_out FROM records WHERE event_name = $1", event_name)
#             return [{"id": record['id'], "created_at": record['created_at'], "code": record['code'], "signed_in": record['signed_in'], "signed_out": record['signed_out'], **json.loads(record['parameters'])} for record in records]
#         except Exception as e:
#             print("Error:", e)
#             raise HTTPException(status_code=500, detail="Failed to read records")
