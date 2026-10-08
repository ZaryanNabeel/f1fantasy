from app import create_app

# Beanstalk's Python platform (and the Procfile) look for a WSGI callable named `application`.
application = create_app()

if __name__ == "__main__":
    application.run(debug=True)
