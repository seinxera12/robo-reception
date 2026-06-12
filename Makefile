.PHONY: up down reset seed logs smoke

up:
	docker compose up -d --build

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up -d --build

seed:
	docker compose exec robo-api python seed.py

logs:
	docker compose logs -f robo-api

smoke:
	pytest tests/integration/ -x -q