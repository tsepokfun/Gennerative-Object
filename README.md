# Generative Object Simulation Framework

**A structural method for answering complex questions using LLM-driven multi-agent simulation.**

This project was my first attempt at building a multi-agent simulation framework using Large Language Models (LLMs). I started it when I was 17, and while it's **not yet complete**, it represents an early exploration of **LLM mission separation** – the idea of breaking down complex tasks into autonomous "Generative Objects" that evolve over time.

> 🎥 **Watch the initial concept video:** [YouTube Link](https://www.youtube.com/watch?v=pQl28n3lJnc)

---

## 🧠 What is this?

The framework creates a simulated timeline where different **Generative Objects (GOs)** – representing distinct groups of people (e.g., leisure travelers, business tourists, Disneyland visitors) – generate actions, update their memory, and interact with a shared knowledge base. Each GO acts autonomously based on its identity, past actions, and global facts.

The result is a **dynamic, emergent narrative** that can answer questions requiring long‑form simulation or scenario analysis.

---

## 🏗️ How It Works

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Fact Base     │     │  Generative     │     │   Timeline      │
│  (shared info)  │◄────┤  Objects (GOs)  │────►│  (daily loop)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        ▲                        │                        │
        │                        ▼                        ▼
        │              ┌─────────────────┐     ┌─────────────────┐
        └──────────────┤  Memory Update  │     │  Action Log     │
                       │  (self‑reflection) │     └─────────────────┘
                       └─────────────────┘
```

**Three core components:**

1. **Generative Object (GO)** – A persona with:
   - `PersonalFact`: who they are (e.g., "Leisure Travelers")
   - `Detail`: background/motivation
   - `Memory`: first‑person recollection (evolves over time)

2. **Fact Base** – Shared context (e.g., tourism statistics, attractions, world events). Injected into every GO prompt.

3. **Timeline** – A day‑by‑day loop:
   - Ask each GO: *"What action would you do today?"*
   - Store the action + duration
   - Update the GO’s memory based on that action

At the end, all actions are summarized into a coherent answer.

---

## 📂 Project Structure

```
.
├── timeLine.py       # Main loop – runs the simulation
├── GF.py             # Global fact store + action log + summary
├── ObjInfo.py        # Generative Object registry (memory/detail)
├── ggg.py            # Gemini LLM wrapper (insert your API key)
├── fact.txt          # Shared knowledge base (edit this for your question)
├── logbook.txt       # Example output from a run
└── README.md         # This file
```

---

## 🚀 Setup & Usage

### 1. Install dependencies
```bash
pip install google-generativeai
```

### 2. Get a Google Gemini API key
- Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
- Create an API key

### 3. Insert your API key
Edit `ggg.py`:
```python
genai.configure(api_key="YOUR_API_KEY_HERE")
```

### 4. Define your question
Edit `fact.txt` – put the background information and context there.
Then set your `Aim` in `timeLine.py`:
```python
Aim = "the tourism of hk in 2008 by info of 2006-2007"
```

### 5. Run the simulation
```bash
python timeLine.py
```

The script will:
- Automatically classify GO groups from the facts
- Simulate every day from start to end date
- Output a final summary

---

## 📊 Example Output (from `logbook.txt`)

For the aim *"tourism of Hong Kong in 2008 based on 2006–2007 data"*, the framework generated:

- **Leisure Travelers** → rode the Peak Tram (4‑5 hrs), visited Disneyland (8‑10 hrs)
- **Business Travelers** → attended conventions, had client dinners in Lan Kwai Fong
- **Disneyland Visitors** → spent full days at the park, experienced new shows
- **Culture Enthusiasts** → explored Man Mo Temple, wandered historic streets

The final summary described Hong Kong as *"a vibrant city blending modern attractions with cultural heritage, catering to diverse visitors."*

> 📄 See the full log in `logbook.txt`

---

## ⚠️ Current Status (Unfinished)

This project is **not yet complete**. What’s missing / planned:

- ✅ Basic simulation loop works
- ✅ GO creation from fact base
- ✅ Action generation & memory updates
- ❌ **Time‑aware alarms** – actions should trigger future events (e.g., a business meeting scheduled for next week)
- ❌ **Inter‑GO communication** – GOs currently act independently, no interaction
- ❌ **Better memory management** – long‑term memory compression (LLM context limits)
- ❌ **Real‑world validation** – comparing simulation outputs to actual historical data
- ❌ **Performance optimization** – currently calls LLM for each GO each day (expensive)

The core idea – **mission separation via autonomous, memory‑augmented objects** – is what I wanted to explore. The YouTube video explains the initial vision.

---

## 🎯 Why I Built This

At 17, I was fascinated by how LLMs could be used not just for single answers, but for **simulating complex systems** – tourism, elections, urban planning. I wanted to see if giving each "agent" a persistent memory and daily routine could produce emergent, realistic behaviour.

This project taught me:
- How to structure multi‑agent prompts
- The importance of memory formatting (first‑person vs. third‑person)
- The challenge of context windows and long‑running simulations
- That LLMs are surprisingly good at role‑playing consistent personas

---

## 🔮 Future Work (If I return to it)

- Implement an **alarm system** (scheduled future actions)
- Add a **message bus** so GOs can react to each other’s actions
- Use a vector database for long‑term memory
- Build a frontend to visualize the timeline
- Run actual historical scenarios and compare to real data

---

## 📚 References

This project was inspired by the paper:  
[Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442) (Park et al., 2023)

---

## 📝 License

MIT – feel free to fork, learn, and improve. If you do something cool, let me know!

---

*Made with 💻 and ☕ by a 17‑year‑old who wanted to see LLMs build stories.*
