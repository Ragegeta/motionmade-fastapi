import time
import openai
import os

client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

start = time.time()
response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "what is 2+2"}],
    max_tokens=50,
    temperature=0.4,
)
elapsed = time.time() - start

print(f"Time: {elapsed:.1f}s")
print(f"Response: {response.choices[0].message.content}")
