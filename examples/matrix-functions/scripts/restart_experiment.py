import numpy as np, scipy.linalg as la, math, sys

def arnoldi_restart(A,b,m,cycles,f):
    n=A.shape[0]
    x=np.zeros_like(b)
    r=b.copy()
    work=0
    for _ in range(cycles):
        # build Krylov basis of length m using Arnoldi (simple Gram-Schmidt)
        V=np.zeros((n,m+1))
        H=np.zeros((m+1,m))
        beta=np.linalg.norm(r)
        if beta==0:
            break
        V[:,0]=r/beta
        work+=n  # matvec for r = A*v (approx count)
        for j in range(m):
            w=A.dot(V[:,j])
            work+=n
            for i in range(j+1):
                H[i,j]=np.dot(V[:,i].conj(),w)
                w-=H[i,j]*V[:,i]
            H[j+1,j]=np.linalg.norm(w)
            if H[j+1,j]==0:
                break
            V[:,j+1]=w/H[j+1,j]
        # compute f(H) via eigendecomp of small H (m x m)
        Hsmall=H[:m,:m]
        evals, evecs = la.eig(Hsmall)
        fH = evecs @ np.diag(np.exp(evals)) @ la.inv(evecs)
        # update solution
        y = beta * la.solve_triangular(H[:m,:], np.eye(m)[:,0], lower=False)  # not exact, placeholder
        # simplified: use approximation x += V[:,:m] @ (fH @ e1)
        e1=np.zeros((m,))
        e1[0]=1.0
        delta = V[:,:m].dot(fH.dot(e1))
        x+=delta
        r=b - A.dot(x)
    err=np.linalg.norm(r)/np.linalg.norm(b)
    return err, work

def sweep():
    n=200
    # eigenvalues uniformly in [-2,2]
    eigs = np.linspace(-2,2,n)
    A = np.diag(eigs)
    b = np.random.randn(n)
    f=lambda z: np.exp(z)  # not used directly
    target=1e-6
    results=[]
    for m in range(5,51,5):
        cycles= int(math.ceil(np.log(target)/ ( -0.2*m)))  # dummy estimate
        err, work = arnoldi_restart(A,b,m,cycles,f)
        results.append((m, cycles, work, err))
    for r in results:
        print(r)
if __name__=='__main__':
    sweep()
