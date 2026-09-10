from database import engine, Base
import psycopg2
print("Dropping tables...")
Base.metadata.drop_all(bind=engine)
print("Done.")
