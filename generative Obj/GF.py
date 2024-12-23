file = open("fact.txt", "r", encoding="utf-8")
fact = file.read()  # Read the entire file at once
file.close()  # Close the file after reading

noOfAction = 0
action = []  # Store actions as tuples: (date, obj_num, action_text, duration)
ct = ""
aim = ""

def upf(f):
    global fact
    fact = f

def gf():
    global fact
    return fact

def upa(n, t):
    action[n] = t

def adda(date, obj_num, action_text, duration):
    global noOfAction
    action.append((date, obj_num, action_text, duration))
    noOfAction += 1
    return noOfAction

def end(Aim, ct):
    global action
    # Generate a summary based on all actions
    
    summary_prompt = f"Based on the following actions taken by different groups of people, generate a summary related to '{Aim}' as of {ct}. Consider the overall impact and trends. Actions: {action}"
    final_summary = ggg.gR(summary_prompt) # use ggg.gR to get summary form LLM
    return final_summary