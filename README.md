Link to frontend: https://github.com/HoriaTG/FishRo-Frontend

# About FishRo

FishRo is an online store for fishing equipment, built with a FastAPI backend and a React frontend.
The platform provides features such as user authentication (login, logout, register), product filtering based on user preferences, a search bar for products, and CRUD operations for administrators through the web interface (adding, updating, and deleting products).

# Backend

The backend of FishRo is implemented using FastAPI and provides the REST API used by the platform.
It manages user authentication, product data, and communication with the database.

**Main functionalities:**

- User authentication

user registration

login and logout

JWT-based authentication

Authorization

role-based access (user, moderator, admin)

protected endpoints using Bearer tokens

Product management

create, update, delete products (admin)

retrieve product list

retrieve product details

Product filtering and search

filtering products based on preferences

search functionality for products

Database management

relational database using SQLite

ORM with SQLAlchemy

Data validation

request and response validation using Pydantic schemas

API security

password hashing with bcrypt

JWT token authentication

CORS configuration for frontend communication

Technologies

FastAPI

SQLAlchemy

SQLite

Pydantic

JWT (python-jose)

Passlib / bcrypt
