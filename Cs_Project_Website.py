

import sqlite3
# Connect to the database
connection = sqlite3.connect("universities.db")

# Create a cursor
cursor = connection.cursor()

# Create a table
cursor.execute("""
CREATE TABLE IF NOT EXISTS universities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    course TEXT,
    deadline TEXT,
    tuition INTEGER
)
""")

# Save changes
connection.commit()

def AddUniversity():
                      
        name = input("University name: ")
        country = input("Country: ")
        course = input("Course: ")
        deadline = input("Deadline: ")
        tuition = input("Tuition: ")

        #its used to enter data into the database or make changes in the database/ Basically editing the database
        cursor.execute("""
        INSERT INTO universities (name, country, course, deadline, tuition)
        VALUES (?, ?, ?, ?, ?)
        """, (name, country, course, deadline, tuition))
        connection.commit()
        #its used to save the data enetered into the database.
def ViewUniversity():
     #Again we are accessing the database to make changes 
        cursor.execute("SELECT * FROM universities")

        universities = cursor.fetchall()

        print("\n=== Saved Universities ===")

        for university in universities:
            print(university)
def SearchUniversity():
    search_name = input("Enter university name: ")

    cursor.execute("""
    SELECT * FROM universities
    WHERE name LIKE?
    """, ("%"+search_name+"%",))

    university = cursor.fetchone()

    if university:
        print("\n=== University Found ===")
        print("ID:", university[0])
        print("Name:", university[1])
        print("Country:", university[2])
        print("Course:", university[3])
        print("Deadline:", university[4])
        print("Tuition:", university[5])

    else:
        print("University not found.")
def UpdateUniversity():
    university_id = int(input("Enter university ID: "))

    new_name = input("New university name: ")
    new_country = input("New country: ")
    new_course = input("New course: ")
    new_deadline = input("New deadline: ")
    new_tuition = (input("New tuition: "))

    cursor.execute("""
    UPDATE universities
    SET name = ?, country = ?, course = ?, deadline = ?, tuition = ?
    WHERE id = ?
    """, (
        new_name,
        new_country,
        new_course,
        new_deadline,
        new_tuition,
        university_id
    ))

    connection.commit()

    if cursor.rowcount > 0:
        print("University updated successfully.")
    else:
        print("University ID not found.")
def DeleteUniversity():
    cursor.execute("SELECT id, name FROM universities")
    universities = cursor.fetchall()

    print("\n=== Universities ===")

    for university in universities:
        print(university[0], "-", university[1])

    university_id = int(input("\nEnter the ID of the university to delete: "))

    cursor.execute("""
    DELETE FROM universities
    WHERE id = ?
    """, (university_id,))

    connection.commit()

    if cursor.rowcount > 0:
        print("University deleted successfully.")
    else:
        print("University ID not found.")






#Main program starts here
while True:

    print("\n=== University Application Tracker ===")
    print("1. Add University")
    print("2. View Universities")
    print("3. Search University")
    print("4. Update University")
    print("5. Delete University")
    print("6. Exit")

    choice = input("Choose an option: ")

    if choice == "1":
        AddUniversity()
                   
    elif choice == "2":
        ViewUniversity()
    elif choice=="3":
        SearchUniversity()
       
    elif choice == "4":
       UpdateUniversity()
        
    elif choice == "5":
        DeleteUniversity()
       
    elif choice == "6":
        print("Closing University Tracker...")
        break

    else:
        print("Invalid option.")


# Close database
connection.close()