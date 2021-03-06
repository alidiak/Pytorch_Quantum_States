#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun 24 16:15:18 2020

@author: alex
"""

import numpy as np
from made import MADE
import autograd_hacks
import torch
from NQS_pytorch import Psi, Op, kron_matrix_gen
import time
import itertools
import copy

# system parameters
b=0.5   # b-field strength
J=1     # nearest neighbor interaction strength
L = 3   # system size
N_samples=100 # number of samples for the Monte Carlo chains

spin=0.5    # routine may not be optimized yet for spin!=0.5
evals=2*np.arange(-spin,spin+1)

# Define operators to use in the Hamiltonian
sigmax = np.array([[0, 1], [1, 0]])
sigmaz = np.array([[1, 0], [0, -1]])

szsz = np.kron(sigmaz, sigmaz)

# initiate the operators and the matrix they are fed
nn_interaction=Op(-J*szsz)
b_field=Op(b*sigmax)

for i in range(L):  # Specify the sites upon which the operators act
    # specify the arbitrary sites which the operators will act on
    b_field.add_site([i])
    nn_interaction.add_site([i,(i+1)%L])
op_list=[] 
for ii in range(2): # make sure to change to match Hamiltonian entered above
    op_list.append(sigmaz)
H_szsz=-J*kron_matrix_gen(op_list,len(evals),L,'periodic').toarray()

op_list2=[]
op_list2.append(sigmax)
H_sx=b*kron_matrix_gen(op_list2,len(evals),L,'periodic').toarray()

H_tot=H_szsz+H_sx

'''####### Define Neural Networks and initialization funcs for psi ########'''

# Neural Autoregressive Density Estimators (NADEs) output a list of 
# probabilities equal in size to the input. Futhermore, a softmax function is 
# handy as it ensures the output is probability like aka falls between 0 and 1.
# For a simple spin 1/2, only a single Lx1 output is needed as p(1)=1-P(-1),
# but with increasing number of eigenvalues, the probability and output becomes
# more complex. 

hidden_layer_sizes=[2*L]
nout=len(evals)*L
#model_r=MADE(L,hidden_layer_sizes, nout, num_masks=1, natural_ordering=True)
#The MADE coded by Andrej Karpath uses Masks to ensure that the
# autoregressive property is upheld. natural_ordering=False 
# randomizes autoregressive ordering, while =True makes the autoregressive 
# order p1=f(s_1),p2=f(s_2,s_1)

#model_i=MADE(L,hidden_layer_sizes, nout, num_masks=1, natural_ordering=True)

def psi_init(L, hidden_layer_sizes,nout, Form='euler'):
    nat_ording=True
    model_r=MADE(L,hidden_layer_sizes, nout, \
                 num_masks=1, natural_ordering=nat_ording)
    model_i=MADE(L,hidden_layer_sizes, nout, \
                 num_masks=1, natural_ordering=nat_ording)

    ppsi=Psi(model_r,model_i, L, form=Form,autoregressive=True)
    
    return ppsi

'''############### Autoregressive Sampling and Psi ########################'''

# initialize/start with a random vector
s0=torch.tensor(np.random.choice(evals,[N_samples,L]),dtype=torch.double)

ppsi=psi_init(L,hidden_layer_sizes,nout,'exponential')

start = time.time()
# Begin the autoregressive sampling and Psi forward pass routine 
def Autoregressive_pass(ppsi,s,evals):
    outc=ppsi.complex_out(s) # the complex output given an ansatz form  
    new_s=torch.zeros_like(s)
    
    if len(s.shape)==2:
        [N_samples,L]=s.shape
        nout=outc.shape[1]
    else:
        [N_samples,L]=1,s.shape[0]
        nout=outc.shape[0]
        outc, new_s=outc[None,:], new_s[None,:] # extra dim for calcs
    
    nevals=len(evals)
    
    # Making sure it is an autoregressive model
    assert nout/L==nevals,"(Output dim)!=nevals*(Input dim), not an Autoregressive NN"
            
    # the full Psi is a product of the conditionals, making a running product easy
    Ppsi=np.ones([N_samples],dtype=np.complex128) 
    
    for ii in range(0, L): # loop over lattice sites
        
        if ii==L: nlim=nout+1 # conditions for slicing. Python doesn't take slice
        else: nlim=nout       # if nout/L=int, so for ii=L, we need (nout+1)/L for 
                            #  outc[:,nout] to be taken.
        # normalized probability/wavefunction
        vi=outc[:,ii:nlim:L] 
        si=s[:,ii] # the input/chosen si (maybe what I'm missing from prev code/E calc)
        # The MADE is prob0 for 0-nin outputs and then prob1 for 
        # nin-2nin outputs, etc. until ((nevals-1)-nevals)*nin outputs 
        tester=np.arange(0,nout);  # print(tester[ii:nlim:L]) # to see slices 
        assert len(tester[ii:nlim:L])==nevals, "Network Output missing in calculation"
        
        exp_vi=np.exp(vi) # unnorm prob of evals 
        norm_const=np.sqrt(np.sum(np.power(np.abs(exp_vi),2),1))
        psi=np.einsum('ij,i->ij', exp_vi, 1/norm_const) # love this tool
        
        born_psi=np.power(np.abs(psi),2)
        
        # satisfy the normalization condition?
        assert np.all(np.sum(born_psi,1)-1<1e-6), "Psi not normalized correctly"
    
        # Now let's sample from the binary distribution
        rands=np.random.rand(N_samples)
        
        psi_s=np.zeros(N_samples, complex) # needed to accumulate Ppsi
        checker=np.zeros(N_samples)
        for jj in range(nevals): 
        
            prev_selection=(si.numpy()==evals[jj]) # which s were sampled 
            # psi(s), accumulate psi for the s that were used to gen samples
            psi_s+=prev_selection*1*psi[:,jj]
            
            # sampling if a<born_psi, sample
            selection=((0<=rands)*(rands-born_psi[:,jj]<=1.5e-7)) 
            # Due to precision have to use <=1e-7 as errors will occur
            # when comparing differences of order 1e-8. (see below check)
            checker+=selection*1
            
            new_s[selection,ii]=evals[jj]
    
            rands=rands-born_psi[:,jj] # shifting the rands for the next sampling
        
        if not np.all(checker)==1: 
            prob_ind=np.where(checker==0)
            raise ValueError("N_samples were not sampled. error at: ", \
                prob_ind, 'with ', rands[prob_ind], born_psi[prob_ind,:])
                
        # Accumulating Ppsi, which is psi_1(s)*psi_2(s)...*psi_L(s)
        Ppsi=Ppsi*psi_s

    return Ppsi, new_s

end = time.time(); print(end - start)

'''################## Test Autoregressive Property #########################'''
#L=2
#nout=len(evals)*L
## get each spin perm
#s2=torch.tensor(np.array(list(itertools.product(evals,repeat=L))),dtype=torch.float)
#
#ppsi=psi_init(L,hidden_layer_sizes,len(evals)*L,'exponential')
#
## Joint probabilities
#wvf,new_s=Autoregressive_pass(ppsi,s2,evals)
#
#def psi_i(ppsi, sn, ii, prev_psi=None):
#    if ii==L: nlim=nout+1 
#    else: nlim=nout  
#    outc=ppsi.complex_out(sn)
#    vi=outc[ii:nlim:L] # p(s0), p(s1)
#    selection=(sn[ii].numpy()==evals)
#    exp_vi=np.exp(vi) 
#    norm_const=np.sqrt(np.sum(np.power(np.abs(exp_vi),2)))
#    if not prev_psi==None:
#        psi=(exp_vi[selection]/norm_const)*prev_psi
#    else:        
#        psi=exp_vi[selection]/norm_const 
#        
#    return psi
#
## computing the conditionals
#ii, jj=0, 0 # lattice, sample number
#psi0=psi_i(ppsi,s2[jj],ii) # first conditional psi0
#psi1=psi_i(ppsi,s2[jj],ii+1)#,prev_psi=psi0) # second conditional psi1
#                            # only enter prev_psi for full mult. conditional
#
## should be equal to the joint probability
#psi00_c=psi0*psi1
#print(wvf[0]-psi00_c)

'''################## Test Energy Calculation #########################'''

ppsi=psi_init(L,hidden_layer_sizes,len(evals)*L,'exponential')
# get each spin perm
s2=np.array(list(itertools.product(evals,repeat=L)))

wvf,new_s=Autoregressive_pass(ppsi,torch.tensor(s2,dtype=torch.float),evals)
wvf=wvf[:,None]

E_sx=np.matmul(np.matmul(np.conjugate(wvf.T),H_sx),wvf)/(np.matmul(np.conjugate(wvf.T),wvf))
E_szsz=np.matmul(np.matmul(np.conjugate(wvf.T),H_szsz),wvf)/(np.matmul(np.conjugate(wvf.T),wvf))
E_tot=np.matmul(np.matmul(np.conjugate(wvf.T),H_tot),wvf)/(np.matmul(np.conjugate(wvf.T),wvf))

N_samples=10000
s0=torch.tensor(np.random.choice(evals,[N_samples,L]),dtype=torch.float)
_,new_s=Autoregressive_pass(ppsi,s0,evals)
start=time.time()
_,s = Autoregressive_pass(ppsi,new_s,evals)
end=time.time(); print(end-start)
H_nn=ppsi.O_local(nn_interaction,s.numpy())
H_b=ppsi.O_local(b_field,s.numpy())

print('For psi= \n', wvf, '\n\n the energy (using exact H) is: ', E_tot, '\n while that ' \
      'predicted with the O_local function is: ', np.sum(np.mean(H_b+H_nn,axis=0)), \
      '\n\n for the exact Sx H: ', E_sx, ' vs ',np.sum(np.mean(H_b,axis=0)), \
      '\n\n for exact SzSz H: ', E_szsz ,' vs ', np.sum(np.mean(H_nn,axis=0)))

''' Ensuring that <psi|H|psi> = \sum_s |psi(s)|^2 e_loc(s)   '''

H_szsz_ex=ppsi.O_local(nn_interaction,s2)
H_sz_ex=ppsi.O_local(b_field,s2)
O_loc_analytic= np.sum(np.matmul((np.abs(wvf.T)**2),(H_szsz_ex+H_sz_ex)))\
 /(np.matmul(np.conjugate(wvf.T),wvf))
E_exact=np.matmul(np.matmul(np.conjugate(wvf.T),H_tot),wvf)/(np.matmul(np.conjugate(wvf.T),wvf))

print('\n\n Energy using O_local in the analytical expression: ',O_loc_analytic, \
      '\n vs. that calculated with matrices: ', E_exact )

'''################## Test DPsi/DW Calculation #########################'''

ppsi=psi_init(L,hidden_layer_sizes,len(evals)*L,'exponential')
original_net=copy.deepcopy(ppsi)

ppsi.real_comp.zero_grad()

pars1=list(ppsi.real_comp.parameters())

dw=0.001 # sometimes less accurate when smaller than 1e-3
with torch.no_grad():
    pars1[0][0][0]=pars1[0][0][0]+dw

# Choose a specific s
s=torch.tensor(np.random.choice(evals,[1,L]),dtype=torch.float)
#s=torch.ones([1,L])

# First let's test the autodifferentiation:
if not hasattr(original_net.real_comp,'autograd_hacks_hooks'):             
    autograd_hacks.add_hooks(original_net.real_comp)
out_0=original_net.real_comp(s)
out_0.mean().backward()
autograd_hacks.compute_grad1(original_net.real_comp)
autograd_hacks.clear_backprops(original_net.real_comp)
pars=list(original_net.real_comp.parameters())
grad0=pars[0].grad1[0,:,:]

#out_0=original_net.real_comp(s)
#out_0.mean().backward()
#pars=list(original_net.real_comp.parameters())
#grad0=pars[0].grad #* (1/N_samples)
      
# Calculate the new and old wavefunctions for this s, numerical dln(Psi)
original_net.Autoregressive_pass(s,evals)
wvf0=original_net.wvf
ppsi.Autoregressive_pass(s,evals)
wvf1=ppsi.wvf
wvf_dif=(np.log(wvf1)-np.log(wvf0))/dw; print('\n Numerical dPsi/dw: ', wvf_dif)
  
out_1=ppsi.real_comp(s)
deriv=(torch.mean(out_1)-torch.mean(out_0))/dw

print('numberical deriv: ', deriv.item(), '\n pytorch deriv: ', grad0[0][0].item(), \
        '\n ratio: ', deriv.item()/grad0[0][0].item() )

# Now calculate the analytically derived derivative of ln(Psi)

# Get my list of vis
outc=original_net.complex_out(s)

Ok=np.zeros([np.shape(s)[0]],dtype=complex)
# Accumulate O_omega1 over lattice sites (also have to see which s where used)
for ii in range(0, L): # loop over lattice sites
#    if ii==L: nlim=nout+1 # conditions for slicing. Python doesn't take slice
#    else: nlim=nout       # if nout/L=int, so for ii=L, we need (nout+1)/L for 
    vi=outc[:,ii::L] 
#    vi=outc[:,2*ii:(2*ii+2)]
#    vi=outc[:,0:2]
    si=s[:,ii].numpy() # the input/chosen si (what I was missing from prev code/E calc)
    exp_vi=np.exp(vi) # unnorm prob of evals 
    
    # pars[0] as we're just looking at a change in 0
    grad0=pars[0].grad1[:,0,:].numpy() # or grad1[:,:,ii]?
    grad0=grad0[:,0] # only comparing to the 0th derivative
    
    # The d_w v_i term (just using exponential form for now)
    dvi=np.einsum('i,ij->ij',grad0,vi) # for a single param should be of size=#evals
    
    # calculating the normalization term in the second part of the deriv
    norm_term=1/np.sum(np.power(np.abs(exp_vi),2),1)
    
    # now for the rest of the second deriv part (depends on dvi)
#    sec_term=np.sum((np.power(exp_vi,2)*dvi)/np.abs(exp_vi),1)*norm_term
    sec_term=0
   
    temp_Ok=np.zeros([np.shape(s)[0]],dtype=complex)
    for jj in range(len(evals)): 
        
        selection=(si==evals[jj]) # which s were sampled 
                                #(which indices correspond to the si)
        sel1=selection*1
        
        # For each eval/si, we must select only the subset vi(si) 
        temp_Ok[:]+=(sel1*dvi[:,jj])#-sel1*sec_term)
    Ok+=temp_Ok-sec_term # manual sum over lattice sites ii=0->N

print('\n\n Ratio numerical/analytic: ', wvf_dif/Ok)

# Peice of Ln(Psi)
out0=original_net.complex_out(s).squeeze()
out1=ppsi.complex_out(s).squeeze()

grads=pars[0].grad1.detach().numpy()
dvi0=0; vi0_l=np.zeros([L,1],dtype=complex)
vs0=0; vs1=0;
sec0=0; sec1=0;
for ii in range(L):
    vi0=out0[ii::L]
    vi1=out1[ii::L]
    
    selection=(s[:,ii]==evals[jj])
    
    vs0+=vi0[selection]
    vs1+=vi1[selection]
    
    dvi0+=vi0[selection]*pars[0].grad1[0][0][0].numpy()
    vi0_l[ii]=vi0[selection]
    
    sec0+=0.5*np.log(np.sum(np.power(np.abs(np.exp(vi0)),2)))
    sec1+=0.5*np.log(np.sum(np.power(np.abs(np.exp(vi1)),2)))
    
ft_diff=(vs1-vs0)/dw; st_diff=(sec1-sec0)/dw
# Making sure things all add up correctly:
assert abs(np.log(wvf1)-(vs1-sec1))<1e-6 and abs(np.log(wvf0)-(vs0-sec0))<1e-6
print('\n\n Numerical dPsi/dw minus first-second term diff', wvf_dif-(ft_diff-st_diff))

print('\n Analytic dPsi/dw: ', Ok)
print('\n First term deriv/difference: ', ft_diff)
print('\n compared to sum(vs0*grad1): ', pars[0].grad1[0][0][0].numpy()*vs0)
print('\n Second term deriv/difference: ', st_diff)


'''################## Test Energy Gradient #########################'''

# function to apply multipliers to the expectation value O_local expression 
def Exp_val(mat,wvf):
    if len(np.shape(mat))==0:
        O_l= np.sum(mat*np.abs(wvf.T)**2)\
        /(np.matmul(np.conjugate(wvf.T),wvf))
    else:
        O_l= np.sum(np.matmul((np.abs(wvf.T)**2),mat))\
        /(np.matmul(np.conjugate(wvf.T),wvf))
    return O_l

#s0=torch.tensor(np.random.choice(evals,[N_samples,L]),dtype=torch.float)
#new_s=ppsi.Autoregressive_pass(s0,evals)
#s=ppsi.Autoregressive_pass(new_s,evals)
#
#[H_nn, H_b]=ppsi.O_local(nn_interaction,s.numpy()),ppsi.O_local(b_field,s.numpy())
#E_loc=np.sum(H_nn+H_b,axis=1)
#E0=np.real(np.mean(E_loc))

#autograd_hacks.add_hooks(ppsi.real_comp)
#outr=ppsi.real_comp(s)
#outr.mean().backward()
#autograd_hacks.compute_grad1(ppsi.real_comp)
#
#mult=torch.tensor(np.real(2*(np.conj(E_loc)-np.conj(E0))/psi0),dtype=torch.float)
#def run(par_ind2,par_ind3):

par_ind2 = 0
par_ind3 = 0    

ppsi=psi_init(L,hidden_layer_sizes,len(evals)*L,'exponential')
original_net=copy.deepcopy(ppsi)

ppsi.real_comp.zero_grad()

pars1=list(ppsi.real_comp.parameters())

dw=0.01 # sometimes less accurate when smaller than 1e-3
with torch.no_grad():
    pars1[0][par_ind2][par_ind3]=pars1[0][par_ind2][par_ind3]+dw

original_net.Autoregressive_pass(torch.tensor(s2,dtype=torch.float),evals)
wvf0=original_net.wvf
ppsi.Autoregressive_pass(torch.tensor(s2,dtype=torch.float),evals)
wvf1=ppsi.wvf
E_tot0=np.matmul(np.matmul(np.conjugate(wvf0.T),H_tot),wvf0)/(np.matmul(np.conjugate(wvf0.T),wvf0))
E_tot1=np.matmul(np.matmul(np.conjugate(wvf1.T),H_tot),wvf1)/(np.matmul(np.conjugate(wvf1.T),wvf1))
dif=(E_tot1-E_tot0)/dw

print(wvf1-wvf0)

# Here calculate the base (unaltered) equivalent expression using O_local 
#new_s=original_net.Autoregressive_pass(torch.tensor(s2,dtype=torch.float),evals)
#s=original_net.Autoregressive_pass(new_s,evals)
#[H_nn_ex, H_b_ex]=original_net.O_local(nn_interaction,s.numpy()),original_net.O_local(b_field,s.numpy())

N_samples=10000
s0=torch.tensor(np.random.choice(evals,[N_samples,L]),dtype=torch.float)
_,new_s=Autoregressive_pass(original_net,s0,evals)
_,s = Autoregressive_pass(original_net,new_s,evals)
H_nn=original_net.O_local(nn_interaction,s.numpy())

[H_nn_ex, H_b_ex]=original_net.O_local(nn_interaction,s.numpy()),original_net.O_local(b_field,s.numpy())
E_loc=np.sum(H_nn_ex+H_b_ex,axis=1)

# check energy0 estimation to exact energy difference
print('Energy Relative Error: ', (E_tot0-np.mean(E_loc))/E_tot0)

_,new_s=Autoregressive_pass(ppsi,s0,evals)
_,s = Autoregressive_pass(ppsi,new_s,evals)
H_nn=ppsi.O_local(nn_interaction,s.numpy())

[H_nn_ex, H_b_ex]=ppsi.O_local(nn_interaction,s.numpy()),ppsi.O_local(b_field,s.numpy())
E_loc1=np.sum(H_nn_ex+H_b_ex,axis=1)
print('Energy Relative Error: ', (E_tot1-np.mean(E_loc1))/E_tot1)

print('O_loc energy difference: ', (np.mean(E_loc1)-np.mean(E_loc))/dw,\
      '\n compared to wvf diff: ', dif)

# Get my list of vis
outc=original_net.complex_out(torch.tensor(s2,dtype=torch.float))

# Get my psi_omega1 gradients (in pars[ii].grad1)
if not hasattr(original_net.real_comp,'autograd_hacks_hooks'):             
    autograd_hacks.add_hooks(original_net.real_comp)
outr=original_net.real_comp(torch.tensor(s2,dtype=torch.float))
outr.mean().backward()
autograd_hacks.compute_grad1(original_net.real_comp)
autograd_hacks.clear_backprops(original_net.real_comp)
pars=list(original_net.real_comp.parameters())

Ok=np.zeros([np.shape(s2)[0]],dtype=complex)
# Accumulate O_omega1 over lattice sites (also have to see which s where used)
for ii in range(0, L): # loop over lattice sites
    if ii==L: nlim=nout+1 # conditions for slicing. Python doesn't take slice
    else: nlim=nout       # if nout/L=int, so for ii=L, we need (nout+1)/L for 
    vi=outc[:,ii:nlim:L]   
    si=s2[:,ii] # the input/chosen si (what I was missing from prev code/E calc)
    exp_vi=np.exp(vi) # unnorm prob of evals 
    
    # pars[0] as we're just looking at a change in 0
    grad0=pars[0].grad1[:,par_ind2,:].numpy() # or grad1[:,:,ii]?
    grad0=grad0[:,par_ind3] # only comparing to the 0th derivative
    
    # The d_w v_i term (just using exponential form for now)
    dvi=np.einsum('i,ij->ij',grad0,vi) # for a single param should be of size=#evals
    
    # calculating the normalization term in the second part of the deriv
    norm_term=1/np.sum(np.power(np.abs(exp_vi),2),1)
    
    # now for the rest of the second deriv part (depends on dvi)
    sec_term=np.sum((np.power(exp_vi,2)*dvi)/np.abs(exp_vi),1)*norm_term
   
    temp_Ok=np.zeros([np.shape(s2)[0]],dtype=complex)
    for jj in range(len(evals)): 
        
        selection=(si==evals[jj]) # which s were sampled 
                                #(which indices correspond to the si)
        sel1=selection*1
        
        # For each eval/si, we must select only the subset vi(si) 
        temp_Ok[:]+=(sel1*dvi[:,jj])#-sel1*sec_term)
    Ok+=temp_Ok-sec_term # manual sum over lattice sites ii=0->N
    

[H_nn_ex, H_b_ex]=original_net.O_local(nn_interaction,s2),original_net.O_local(b_field,s2)
E_loc=np.sum(H_nn_ex+H_b_ex,axis=1)

deriv_E0=Exp_val(np.conj(Ok)*E_loc,wvf0)+Exp_val(Ok*np.conj(E_loc),wvf0)-\
Exp_val(E_loc,wvf0)*(Exp_val(np.conj(Ok),wvf0)+Exp_val(Ok,wvf0))

print('\n Expecation val deriv: ', deriv_E0, '\n vs numerical wvf energy diff: ', dif)
print(dif/deriv_E0)

#    return

'''#### Test model in Ppsi Object Construction & with Methods  ####'''

# Test Autograd_hacks (works with modification I added that applies masks)
ppsi=psi_init(L,hidden_layer_sizes,nout,'euler')
if not hasattr(ppsi.real_comp,'autograd_hacks_hooks'):             
    autograd_hacks.add_hooks(ppsi.real_comp)
outr=ppsi.real_comp(s0)
outr.mean().backward()
autograd_hacks.compute_grad1(ppsi.real_comp) #computes grad per sample for all samples
autograd_hacks.clear_backprops(ppsi.real_comp)
p_r=list(ppsi.real_comp.parameters())

for param in p_r:
    print(torch.max(param.grad-param.grad1.mean(0)))

# test SR
E_loc=np.sum(H_nn+H_b,1)
ppsi.SR(s0,E_loc)
# Also will need some adjustments
# The m=outr(s) and complex_out(s) are no longer N_samples,1. Need to add
# method that converts ppsi.real_model(s) to conditional psi coef list when 
# the model is autoregressive. (similarly for complex_out).

