"Docekr"
docker-compose down
docker-compose build --no-cache api
docker-compose up -d
docker ps

"Docker Logs"

docker-compose logs
docker-compose logs db
docker-compose logs redis
docker-compose logs api
docker-compose exec api alembic upgrade head
docker-compose exec api alembic current

"Starting the backend"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000



