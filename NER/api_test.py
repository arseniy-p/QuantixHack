import asyncio
import aiohttp
import json

# ИЗМЕНЕНИЕ ЗДЕСЬ: используем https вместо http
API_URL = "https://quantixhack.duckdns.org/claims/search"

# JSON-пейлоад, который мы отправляем
PAYLOAD = {"text": "John Smith"}

async def test_john_smith_search():
    """
    Отправляет один POST-запрос к API поиска заявок с
    заданным пейлоадом для "John Smith" и выводит результат.
    """
    print(f"--- Подготовка запроса к: {API_URL} ---")
    print(f"Отправляемый пейлоад: {json.dumps(PAYLOAD, indent=2)}")
    
    # Используем aiohttp для асинхронных HTTP-запросов
    async with aiohttp.ClientSession() as session:
        try:
            # Выполняем POST-запрос с указанным JSON
            async with session.post(API_URL, json=PAYLOAD, timeout=15) as response:
                
                # Выводим HTTP-статус код ответа сервера
                print(f"\n--- Ответ Сервера ---")
                print(f"Статус-код: {response.status}")
                
                # Проверяем, был ли запрос успешным (например, статус 200 OK)
                if response.ok:
                    # Читаем тело ответа в формате JSON и выводим его
                    response_data = await response.json()
                    print("Тело ответа (JSON):")
                    # Используем json.dumps для красивого вывода
                    print(json.dumps(response_data, indent=2))
                else:
                    # Если была ошибка, выводим ее текст
                    error_text = await response.text()
                    print(f"Тело ошибки: {error_text}")

        except aiohttp.ClientError as e:
            print(f"\n--- Ошибка ---")
            print(f"Произошла ошибка соединения: {e}")
        except asyncio.TimeoutError:
            print(f"\n--- Ошибка ---")
            print("Тайм-аут запроса.")
        except Exception as e:
            print(f"\n--- Произошла непредвиденная ошибка ---")
            print(e)


if __name__ == "__main__":
    # Запускаем асинхронную функцию
    asyncio.run(test_john_smith_search())