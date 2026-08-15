import random

def strassen(A,B):
    a11,a12 = A[0]
    a21,a22 = A[1]
    b11,b12 = B[0]
    b21,b22 = B[1]
    p1 = (a11 + a22)*(b11 + b22)
    p2 = (a21 + a22)*b11
    p3 = a11*(b12 - b22)
    p4 = a22*(b21 - b11)
    p5 = (a11 + a12)*b22
    p6 = (a21 - a11)*(b11 + b12)
    p7 = (a12 - a22)*(b21 + b22)
    c11 = p1 + p4 - p5 + p7
    c12 = p3 + p5
    c21 = p2 + p4
    c22 = p1 - p2 + p3 + p6
    return [[c11,c12],[c21,c22]]

def direct(A,B):
    return [[A[0][0]*B[0][0]+A[0][1]*B[1][0], A[0][0]*B[0][1]+A[0][1]*B[1][1]],
            [A[1][0]*B[0][0]+A[1][1]*B[1][0], A[1][0]*B[0][1]+A[1][1]*B[1][1]]]

random.seed(0)
ok=True
for _ in range(1000):
    A=[[random.randint(-10,10) for _ in range(2)] for __ in range(2)]
    B=[[random.randint(-10,10) for _ in range(2)] for __ in range(2)]
    if strassen(A,B)!=direct(A,B):
        ok=False
        print("Mismatch",A,B)
        break
print("All tests passed" if ok else "Failed")
