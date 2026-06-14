.PHONY: up down reset seed logs smoke

up:
	docker compose up -d --build

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up -d --build

seed:
	docker compose exec reception-api python seed.py

logs:
	docker compose logs -f reception

smoke:
	pytest tests/integration/ -x -q