from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://ecommerce_user:ecommerce_pass@127.0.0.1:5433/ecommerce"

try:
    engine = create_engine(DATABASE_URL)

    with engine.connect() as connection:
        result = connection.execute(text("SELECT version()"))
        print("Connection Successful!")
        print(result.scalar())

except Exception as error:
    print("Connection Failed!")
    print(error)