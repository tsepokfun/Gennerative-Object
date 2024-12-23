import google.generativeai as genai

#api key
genai.configure(api_key="Your api key.")
#api key

#model choose 
model = genai.GenerativeModel("gemini-1.5-flash")
#model choose

chat = model.start_chat(
history=[
    {"role": "user", "parts": "Hello"},
    {"role": "model", "parts": "Great to meet you. What would you like to know?"},
]
)

def gR(q):
    response = chat.send_message(q)
    return response.text