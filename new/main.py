#使用session做簡單的使用者認證，管理狀態
#Jinja2 render html templates
#Request class從fastapi被imported
#記得安裝mysql-connector-python
#HTTPException是做什麼的?
from fastapi import FastAPI, Form, Request, HTTPException, Query, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
import mysql.connector
from mysql.connector import errorcode, Error
from pydantic import BaseModel
from typing import Optional

#從FastAPI class創造一個Object
#這個object作為主要的處理器，處理所有的configurations(設定), routes, middleware, and event listeners
#她管理server和web application之間的互動，處理被送進來的request，也送出response給clients
app = FastAPI()
#session是一種儲存機制，目的是儲存登入訊息，sessionMiddleware的session數據是直接加密後儲存在cookie裡面
#需要一個密鑰來加密存在cookie裡面的session data
app.add_middleware(SessionMiddleware, secret_key="your_secret_key_here")
#jinja2是用來render在"templates"資料夾裡面的html templates
templates = Jinja2Templates(directory="templates")


#這個endpoint處理"被送進來的username、password"，並傳送數據(post)給其他的endpoints
#endpoint是指一個url pattern，這個url pattern被server曝光給客戶，讓客戶能跟這個url互動
#客戶跟endpoint互動的方法有"GET/ POST/ PUT/ DELETE etc"

# Database connection parameters
db_config = {
    'user': 'wehelp',
    'password': 'wehelp',
    'host': 'localhost',
    'database': 'website',
    'raise_on_warnings': True
}


#測試中____________________________________________________________________________________________


# Pydantic models for request and response
#因為使用者會透過html傳送GET request過來要資料，我們先把要給使用者的資料用class做一個規範整理
#如果要傳給使用者的資料不符合這個規定，就會有error
class MemberResponse(BaseModel):
    id: int
    name: str
    username: str

class MemberResponseWrapper(BaseModel):
    data: Optional[MemberResponse]


# API endpoint to get member data by real name
#this is a decorator tells FASTAPI to create a route with path "/api/member" 
#get 代表這個route會respond to HTTP GET requests
#(A,B)裡面的B是讓FastAPI知道要送回給使用者的data要符合這個class的格式以及轉成JSON檔
@app.get("/api/member", response_model=MemberResponseWrapper)
def read_member(username: str = Query(...)):
    try:
        conn = mysql.connector.connect(
            user='wehelp', 
            password='wehelp', 
            host='localhost', 
            database='website'
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, username FROM member WHERE username = %s", (username,))
        member = cursor.fetchone()
        print(member)
        cursor.close()
        conn.close()

        if not member: 
            return {"data": None}

        return {"data": member}  # This should be a dictionary directly compatible with the MemberResponse model

    except mysql.connector.Error as e:
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.patch("/api/member", response_model=dict)
async def update_name(request:Request):

    member_id = request.session.get('id')
    print(member_id)
    content_type = request.headers.get('content-Type')
    #沒有id或不是json格式的話，送error回去
    if not member_id or content_type != "application/json":
        request.session.clear()
        return JSONResponse(content={"error": True})
    
    data_patch = await request.json()
    new_name = data_patch["name"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE member SET name = %s WHERE id = %s", (new_name, member_id))
        conn.commit()
        #確認被更改的mysql資料存不存在
        if cursor.rowcount == 0:
            return JSONResponse(content={"error": True})
        request.session['name'] = new_name
        return {"ok": True}
    except Exception as e:
        conn.rollback()
        print(f"An error occurred: {e}")
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": True}) 
    finally:
        cursor.close()
        conn.close()


        


#測試中____________________________________________________________________________________________




def get_db_connection():
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Something is wrong with your user name or password")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            print("Database does not exist")
        else:
            print(err)
    return None

@app.post("/signup")
async def signup(signupRealname: str = Form(...), signupUsername: str = Form(...), signupPassword: str = Form(...)):
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    #create a cursor
    cursor = conn.cursor()
    
    # Check if the username already exists
    #在mysql執行指令
    cursor.execute("SELECT * FROM member WHERE username = %s", (signupUsername,))
    #fetch the 1st single row of data result 拿結果
    user = cursor.fetchone()
    
    if user:
        #close cursor and connection
        cursor.close()
        conn.close()
        return RedirectResponse(url="/error?message=Repeated username", status_code=303)
    
    # Insert new user if username not found
    try:
        cursor.execute(
            "INSERT INTO member (name, username, password) VALUES (%s, %s, %s)",
            (signupRealname, signupUsername, signupPassword)
        )
        #對database的修改只有在commit()以後才會真的改變，任何操作失敗，database都可以回復到之前的狀態
        conn.commit()
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=500, detail=str(err))
    
    cursor.close()
    conn.close()
    return RedirectResponse(url="/", status_code=303)


#增加訊息
@app.post("/createMessage")
async def add_message(request: Request, newContent: str = Form(...)):
    member_id = request.session.get('id')
    #沒有id的話，送到error頁面
    if not member_id:
        request.session.clear()
        return RedirectResponse(url='/error?message=Session not found', status_code = 303)

    try:
        with get_db_connection() as conn:
            #連線有問題的話
            if conn is None:
                raise HTTPException(status_code=500, detail="Database connection failed")
            
            #使用with，做完馬上關掉conn&cursor
            with conn.cursor() as cursor:
                #insert new message
                cursor.execute(
                    "INSERT INTO message (member_id, content, like_count, time) VALUES (%s, %s, %s, NOW())", 
                    (member_id, newContent, 0)
                )
                conn.commit()
    #HTTPException的作用是可以跟client用HTTP protocode溝通error，所以把這個跟普通的Exception分開
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        request.session.clear()
        return RedirectResponse(url='/', status_code=500)
    #如果try block成功執行，沒有任何error的話，就重新送回member page
    else:
        return RedirectResponse(url='/member', status_code=303)
        

#刪除訊息
@app.post("/deleteMessage")
async def delete_message(request: Request, message_id: int = Form(...)):
    member_id = request.session.get('id')
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = conn.cursor()
    #確定要刪的message屬於signed-in user
    cursor.execute(
        "DELETE FROM message WHERE id = %s AND member_id = %s", (message_id, member_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return RedirectResponse(url='/member', status_code=303)


#登入會員
@app.post("/signin")
#request是一個參數，並註解Request。 註解代表講清楚這個變數包含了什麼type of data或是這個函數應該期待什麼type的data會輸入或返回
#後面兩個參數從表格資料提取username & password
async def handle_login(request: Request, username: str = Form(None), password: str = Form(None)):
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    #create a cursor
    cursor = conn.cursor()

    # Check if the username already exists
    #在mysql執行指令
    cursor.execute("SELECT id, name, username, password FROM member WHERE username = %s", (username,))
    #fetch the 1st single row of data result 拿結果
    user = cursor.fetchone()

    if user is None:
        cursor.close()
        conn.close()
        return RedirectResponse(url='/error?message=Username or password is not correct', status_code = 303)
    
    #extract data from the tuple(a,b,c) in the query and give every element a variable
    #例如 member_id = tuple('member_id')
    stored_member_id, stored_realname, stored_username, stored_password = user

    if password == stored_password:
        #密碼正確的話，把資料存進session
        request.session['signed_in'] = True
        request.session['id'] = stored_member_id
        request.session['name'] = stored_realname
        request.session['username'] = stored_username

        cursor.close()
        conn.close()
        return RedirectResponse(url='/member', status_code=303)
    else:
        #密碼錯誤
        request.session.clear()
        cursor.close()
        conn.close()
        return RedirectResponse(url='/error?message=Username or password is not correct', status_code = 303)


#處理登出
@app.get("/signout")
async def signout(request: Request):
    #若是收到signout的要求，把session的value設定為False，代表已登出
    #redirect到首頁
    #request.session['signed_in'] = False
    request.session.clear()
    return RedirectResponse(url='/', status_code=303)


#進入會員頁前的中繼站API
@app.get("/member")
async def member_page(request: Request):
    
    #如果收到的session是空的或錯誤，redirect到首頁
    if not (request.session.get('signed_in') and 'id' in request.session):
        request.session.clear()
        return RedirectResponse(url='/', status_code=303)  

    #如果收到的session裡面的value是True，回傳給user我們做的html file
    #再次verify
    member_id = request.session.get('id')
    #把程式碼寫在try裡面，是跟Python說"試著執行這個程式碼，但如果有error，就用我指定的方式處理"
    #避免crash，可以搭配except、else、finally、with
    try:
        conn = get_db_connection()
        #如果連線中斷了，送使用者回老家
        if conn is None:
            request.session.clear()
            return RedirectResponse(url='/error?message=Database connection failed', status_code=500)
        
        #使用with conn+with conn.cursor() as cursor可以確保connection+cursor都被關掉(即使有exception)
        #取代cursor.close()、conn.close()
        with conn:
            with conn.cursor() as cursor:
                #如果連線成功
                #照著session裡面的id到member table拿資料
                cursor.execute("SELECT id, name, username FROM member WHERE id = %s", (member_id,))        
                user = cursor.fetchone()

                #如果用戶id不存在，送回老家
                if user is None:
                    request.session.clear()
                    return RedirectResponse(url='/', status_code=303)  
                
                #用戶存在的話，才開始fetch message from "message" table in mysql
                #messages裡面資料的順序(id, member_id, content, member的name)
                #這裡的m.time很重要，因為兩個table都有time column，如果沒有寫照哪一個排列，會有錯誤
                cursor.execute("""
                               
                                SELECT m.id, m.member_id, m.content, mb.name 
                                FROM message m
                                JOIN member mb ON m.member_id = mb.id
                                ORDER BY m.time DESC
                """)
                messages = cursor.fetchall()    

            #'用戶'為預設值，如果database裡面剛好沒有名字的話
            realname = request.session.get('name', '預設用戶名稱')      
            response = templates.TemplateResponse("member.html", {
                "request": request, 
                "realname": realname,
                "messages": messages,
                "member_id": member_id
            })
            #確保這個網頁不會被存在使用者的cache裡面，在沒認證的狀態下被revisit
            response.headers['Cache-Control'] = 'no-store'
            return response 
    # e是一個 variable 用來抓住 exception object，這個object包含細節資訊，可以印出來看錯誤是什麼
    except Exception as e:
        request.session.clear()
        return RedirectResponse(url='/', status_code=500) 


#使用了Jinja2在error.html裡面插入error message
@app.get("/error")
async def error_page(request: Request):
    #從request的query parameters(查詢參數)中找'message'；如果message=None的話，就預設為'unknown error'
    message = request.query_params.get('message', 'Unknown error')
    return templates.TemplateResponse("error.html", {"request": request, "message": message})


#提供登入的頁面signin.html
#使用Jinja2傳遞Request object到templates，這樣我們在templates裡面也可以使用request的內容
@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("signin.html", {"request": request})






