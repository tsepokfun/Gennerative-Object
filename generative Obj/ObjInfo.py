noOfObj = 0
PersonalFact = []
Detail = []
Memory = []

def getData(n):
    return [PersonalFact[n], Detail[n], Memory[n]]

def add(P, D, M):  # Correctly takes 3 arguments now
    global noOfObj
    PersonalFact.append(P)
    Detail.append(D)
    Memory.append(M)
    noOfObj += 1
    return noOfObj

def upd(no, P, D, M):
    PersonalFact[no] = P
    Detail[no] = D
    Memory[no] = M
