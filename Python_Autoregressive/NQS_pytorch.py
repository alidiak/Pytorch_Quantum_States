#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May 12 14:26:01 2020

Here we keep classes and functions for the Pytorch Quantum States library.


@author: Alex Lidiak
"""

import itertools
import numpy as np
import torch
import torch.nn as nn
from autograd_hacks_master import autograd_hacks

class Op:
    
    def __init__(self, matrix):
        self.matrix=matrix
        self.sites=[]
        
    def add_site(self,new_site):
        self.sites.append(new_site)
        
    # Could potentially add the O_loc function here as a method to Op
        
        return

'''###################### Complex Psi ######################################'''
# can change all s to self.samples if running optimization
class Psi:
    ''' potential improvement of the above class would be to make s a property 
    (less re-entering of s). '''
    def __init__(self, real_comp, imag_comp, L, evals=None, form='euler', dtype=torch.float,
                 autoregressive=False):
        # options for form are 'euler' or 'vector' - corresponding to 2 forms 
        # of complex number notation
        self.complex=0
        self.L=L
        self.samples=0
        self.form=form
        self.re=False
        if self.form.lower()=='real': self.re=True # no imag_comp if net is real
        
        # TODO: make sure evals can be arbitrary list and still be compatible
        if evals is None: 
            spin = 0.5 # presumambly will be entered by the user in later versions
            self.evals=2*np.arange(-spin,spin+1)
        else: self.evals=np.array(evals)
        
        # Code for adjusting class to different datatypes
        if isinstance(dtype,str):
            if dtype.lower()=='double':
                self.dtype=torch.double
            else: self.dtype=torch.float
        else:
            self.dtype=dtype
        if self.dtype==torch.double:
            self.real_comp=real_comp.double() # converts model params to double acc.
            if not self.re: self.imag_comp=imag_comp.double()
            self.complextype=np.complex128
        else:
            self.real_comp=real_comp
            if not self.re: self.imag_comp=imag_comp
            self.complextype=np.complex64
            
        # Boolean of the class specifying if it is an autoregressive model
        self.autoregressive=autoregressive # default is false
        if self.autoregressive: # Adding autoregressive specific properties
            self.wvf=0 # accumulated psi
            
            # These are extra properties/traits the Autoregressive QNADE code needs
            self.supported_layers = ['Linear'] # TODO: add 'conv' was capability is added
            assert(self.L==imag_comp[0].in_features), 'incompatible real and imaginary input sizes'
            assert(self.L*len(self.evals)==self.real_comp[-1].out_features), \
            'The final/output layer size must be equal to the system size times the number of evals'
            
            
    # Method to return the complex number specified by the state of the 
    # 2 ANNs real_comp and imag_comp and an input state s
    def complex_out(self, s): # complex number for each sample
        
        if not self.form.lower()=='real':
            self.complex=np.zeros(s.size(0),dtype=self.complextype)
            
        if self.form.lower()=='euler':
            self.complex=self.real_comp(s).detach().numpy()*    \
            np.exp(1j*self.imag_comp(s).detach().numpy())
            
        elif self.form.lower()=='vector':
            self.complex=self.real_comp(s).detach().numpy()+    \
            1j*self.imag_comp(s).detach().numpy()
            
        elif self.form.lower()=='exponential':
            self.complex=np.exp(self.real_comp(s).detach().numpy()+    \
            1j*self.imag_comp(s).detach().numpy())
            
        elif self.form.lower()=='real':
            self.complex=self.real_comp(s).detach().numpy()
            
        else:
            raise Warning('Specified form', self.form, ' for complex number is'\
            ' ambiguous, use either "euler": real_comp*e^(i*imag_comp), "vector":'\
            ' real_comp+1j*imag_comp, or "exponential": e^(real_comp+i*imag_comp).'\
            ' This output was calculated using "euler" (default).')
            self.form='euler'
            self.complex=self.real_comp(s).detach().numpy()*    \
            np.exp(1j*self.imag_comp(s).detach().numpy())
            
        return self.complex

    '''############################ O_local #######################################
    Now find O_local where O is an arbitrary operator acting on sites entered. This 
    function returns the O_local operator summed over the 'allowed' transitions 
    between the given input spin s and any non-zero transition to spin config s'. 
    This operator also depends upon the current wavefunction psi. '''
    def O_local(self, operator, s): 
        
        # Testing if it is a Hamiltonian object
    #    if hasattr(operator,'Op_list'):
    #        N_ops=len(operator.Op_list)
    #    else:
    #        N_ops=1
    #        
        #if not np.all(np.conjugate(np.transpose(operator.matrix))==operator.matrix):
        #    raise Warning('Operator matrix ', operator.matrix, 'is not Hermitian,'\
        #                  ' Observable may be non-real and unphysical')
                     # using CUDA devices could potentially accelerate this func?
        sites=operator.sites.copy()
        
        [n_sites,op_span]= np.shape(sites) # get lattice list length and operator span
                                            # former is often equal to L (lat size) if applied to all sites
        [N_samples,L]=np.shape(s)  # Get the number of samples and lattice size from samples
            
        evals=self.evals
        dim=int(len(evals))   
        
        op_size=np.log((np.shape(operator.matrix)[0]))/np.log(dim)
        if not op_size==op_span:
            raise ValueError('Operator size ', op_size, ' does not match the number' \
                             ' of sites entered ', op_span, 'to be acted upon')
        
        O_loc=np.zeros([N_samples,L],dtype=self.complextype) 
        #this construction allows us to get local expectation vals
        # and the energy for each sample (which we can use to backprop)
        
        # cycle through the sites and apply each operator to state s_i (x s_i+1...)
        for i in range(n_sites):
            
            s_prime=s.copy() # so it's a fresh copy each loop
            
            # Set up spin config representation in Sz basis for just the acted upon spins
            # need to generalize for arbitrary spin
            sz_basis=np.zeros([N_samples,op_span,dim])
            s_loc=s[:,sites[i]]
            # can iterate over this for spin!=0.5. use evals
            sz_basis[np.where(s_loc==1)[0],np.where(s_loc==1)[1],:]=np.array([1,0]) 
            sz_basis[np.where(s_loc==-1)[0],np.where(s_loc==-1)[1],:]=np.array([0,1])
            
            if op_span>1: # extend the size of the basis for multi-site operators
                basis=sz_basis[:,0,:]
                for j in range(1,op_span): 
                    basis=np.einsum('nk,nl->nkl',basis,sz_basis[:,j,:]).reshape(basis.shape[0],-1)
                    # einstein summation func, forces kron product over 2nd axis by 
                    # by taking matching inputs from the nth col, avoids kron over samples
                    # cycle through the states acted on by the multi-site operator
            else:
                basis=sz_basis[:,0,:]
                
            # S[sites[i]] transformed by Op still in extended basis
            # Should not matter which side the operator acts on as Op must be hermitian
            # as we act on the left here, 
            xformed_state=np.squeeze(np.matmul(basis,operator.matrix)) 
            
    #        if np.all((basis>0)==(np.abs(xformed_state)>0)):
    #            # can skip changing s', nothing's changed in the basis
    #            basis[basis==0]=1 # just doing this so that there's no division by 0
    #            div=xformed_state/basis
    #            multiplier=div[div>0] 
    #            # returns all of the differences in magnitude of the otherwise unchanged basis state
    #            pass
    #        else:
    
            # just so the alg can handle single sample input. adds a singleton dim
            if len(xformed_state.shape)==1:
                xformed_state=xformed_state[None,:]
    
            ## Generating all possible permutations of the local spins
            perms=np.array(list(itertools.product(evals,repeat=op_span)))
            
            # do a loop over all of the possible permutations
            for kk in range(len(perms)): # xformed_state.shape[1]
                
                # change the local spins in s' for each config
                s_prime[:,sites[i]]=perms[-(kk+1)]
                # -(kk+1) is used because the ordering is opposite of how the 
                # slicing is organized. Ex, -1,-1 corresponds to the last 
                # slice (0,0,0,1) and 1,1 to the first (1,0,0,0) with the 
                # 1 state = (1,0) and -1 state = (0,1) convention.
                
                if self.autoregressive:
                    wvf_prime, _ = self.QNADE_pass(x=torch.tensor(s_prime,dtype=self.dtype))
                    _, _ = self.QNADE_pass(x=torch.tensor(s,dtype=self.dtype)) # will update self.wvf
                    log_psi_diff=np.log(wvf_prime)-np.log(self.wvf)
                    O_loc[:,i]+= xformed_state[:,kk]*np.exp(log_psi_diff)
                elif self.form.lower()=='real': # log sensitive when real
                    psi_div=self.complex_out(torch.tensor(s_prime,\
                    dtype=self.dtype)).flatten()/self.complex_out(\
                    torch.tensor(s,dtype=self.dtype)).flatten()
                    O_loc[:,i]+= xformed_state[:,kk]*psi_div
                else:
                    log_psi_diff=np.log(self.complex_out(torch.tensor(s_prime,\
                    dtype=self.dtype)).flatten())-np.log(self.complex_out(\
                    torch.tensor(s,dtype=self.dtype))).flatten()
                    O_loc[:,i]+= xformed_state[:,kk]*np.exp(log_psi_diff)
                # each slice of the transformed state acts as a multiplier to 
                # its respective local spin configuration state
                    
        return O_loc

    ''' #################### OPTIMIZATION METHODS ##########################'''
    
    '''##################### Energy Gradient ############################'''
    ''' This method will apply the energy gradient to each ANN network param for 
    a given form of Psi. It does simple gradient descent (no SR or anything).
    It does so given an E_local, Energy E, and wavefunc Psi over sample set s.'''

    def energy_gradient(self, s, E_loc, E0=None):#, cutoff=1e-8): 
        
        if E0 is None:
            E0=np.real(np.mean(E_loc))
            
        N_samples=s.shape[0]
        
#        if self.autoregressive:
            
        # Calculate all of the different multipliers for each form
        if self.form.lower()=='vector':               
            m_r=(1/self.complex_out(s)).squeeze()
            m_i=1j*m_r
            
        elif self.form.lower()=='euler' or self.form.lower()=='exponential'\
             or self.form.lower()=='real':
                 
            if self.form.lower()=='euler' or self.form.lower()=='real':
                m_r=1/self.real_comp(s).detach().numpy().squeeze()
                
            else:
                m_r=(np.ones([N_samples,1])).squeeze()
            m_i=(np.ones([N_samples,1])*1j).squeeze()            
            
        E_arg=(np.conj(E_loc)-np.conj(E0))
        
        for ii in range(2):
            if ii==0: # Compute GD for real component
                model=self.real_comp; m=m_r
            else: # Compute GD for imag component
                model=self.imag_comp; m=m_i
                
            model.zero_grad()
            
            if not hasattr(model,'autograd_hacks_hooks'):             
                autograd_hacks.add_hooks(model)
            outr=model(s)
            outr.mean().backward()
            autograd_hacks.compute_grad1(model) #computes grad per sample for all samples
            
            pars=list(model.parameters())
                
            for param in pars:
                if len(param.size())==2:#different mat mul rules depending on mat shape
                    ein_str="i,ijk->ijk"
                elif len(param.size())==1:
                    ein_str="i,ik->ik"
                with torch.no_grad():      
                    param.grad=torch.einsum(ein_str,torch.tensor(np.real(2*E_arg*m)\
                    ,dtype=self.dtype),param.grad1).mean(0) # force/DE term
            
            autograd_hacks.clear_backprops(model)
            # exits for loop so it is only applied to real comp
            if self.form.lower()=='real':
                break 
            
        return

    def energy_gradient1(self, s, E_loc, E=None): # add Pytorch optimizer) (fixed lr for now)
        
        if E is None:
            E=np.mean(E_loc)
                
        E=np.conj(E)
        E_loc=np.conj(E_loc)
        diff=(E_loc-E)
        
        self.real_comp.zero_grad()
        if not self.re: self.imag_comp.zero_grad()
        # should be the simpler form to apply dln(Psi)/dw_i
        if self.form.lower()=='real':
            outr = self.real_comp(s).flatten()
            mult=torch.tensor(np.real(2*diff),dtype=self.dtype)
            (outr.log()*mult).mean().backward()
            
        elif self.form.lower()=='euler' or self.form.lower()=='exponential':
            
            outr = self.real_comp(s).flatten()
            outi = self.imag_comp(s).flatten()
            
            # each form has a slightly different multiplication form
            # MODULUS
            mult=torch.tensor(np.real(2*diff),dtype=self.dtype)
            if self.form.lower()=='euler':
#                assert torch.all(outr>0), "log of 0 or negative number"
                (outr.log()*mult).mean().backward()
                
            elif self.form.lower()=='exponential':
                (mult*outr).mean().backward() 
            # calling this applies autograd to tensor .grad object i.e. out*mult
            # which corresponds to dpsi_real(s)/dpars. 
            
            # ANGLE
            mult = torch.tensor(2*np.imag(-E_loc),dtype=self.dtype)
            (mult*outi).mean().backward()
            
        # Although the speed difference is not significant, the above is still 
        # faster than using the autograd_hacks per sample gradient version used
        # for the vector gradients below
            
        elif self.form.lower()=='vector':
            if np.all(self.complex==0): 
        # could create errors if doesn't use the updated ppsi and new s
        # but each call of O_local redefines the .complex
                self.complex_out(s) # define self.complex
              
            # hooks accumulate the gradient per sample into layers.backprops_list
            # only called once otherwise extra grads are accumulated
            if not hasattr(self.real_comp,'autograd_hacks_hooks'):             
                autograd_hacks.add_hooks(self.real_comp)
            if not hasattr(self.imag_comp,'autograd_hacks_hooks'): 
                autograd_hacks.add_hooks(self.imag_comp)
            outr=self.real_comp(s)
            outi=self.imag_comp(s)
            outr.mean().backward()
            outi.mean().backward()
            autograd_hacks.compute_grad1(self.real_comp)
            autograd_hacks.compute_grad1(self.imag_comp)
            
            m=2*(np.conj(E_loc)-np.conj(E))/self.complex.squeeze()
            
            p_r=list(self.real_comp.parameters())
            p_i=list(self.imag_comp.parameters())
            
            # multiplying the base per sample grad in param.grad1 by the dPsi
            # derivative term and assigning to the .grad variable to be applied 
            # to each parameter variable with the apply_grad function. 
            for param in p_r:
                if len(param.size())==2:
                    ein_str="i,ijk->ijk"
                elif len(param.size())==1:
                    ein_str="i,ik->ik"
                param.grad=torch.einsum(ein_str,torch.tensor(np.real(m)\
                    ,dtype=self.dtype),param.grad1).mean(0)
            for param in p_i: # dPsi here is 1j*dPsi of real
                if len(param.size())==2:
                    ein_str="i,ijk->ijk"
                elif len(param.size())==1:
                    ein_str="i,ik->ik"
                param.grad=torch.einsum(ein_str,torch.tensor(np.real(1j*m)\
                    ,dtype=self.dtype),param.grad1).mean(0)
          
            # clear backprops_list for next run
            autograd_hacks.clear_backprops(self.real_comp)
            autograd_hacks.clear_backprops(self.imag_comp)
            
        return 

    '''################# Autoregressive Gradient Descent ###################'''

    def autoregressive_grad(self, E_loc, s, evals, comp):
        N_samples=s.shape[0]
        if comp.lower()=='real':
            model=self.real_comp
        else: model=self.imag_comp
        
#        E0=np.real(np.mean(E_loc))
        E_arg=(np.conj(E_loc)-np.conj(np.mean(E_loc)))
        
        # Get my list of vis
        outc=self.complex_out(s)
        if not hasattr(model,'autograd_hacks_hooks'):             
            autograd_hacks.add_hooks(model)
        out=model(s)
        pars=list(model.parameters())
        
        # initializing some numpy lists to record both the Ok and be a temporary holder
        # for the grad of each eval (which changes each ii, kk loop, but most efficient to initalize once)
        E_grad= [[] for i in range(len(pars))]
        gradii= [[] for i in range(len(pars))]
#        model.zero_grad()
        for rr in range(len(pars)):
            if len(pars[rr].size())==2:
                [sz1,sz2]=[pars[rr].size(0),pars[rr].size(1)]
            else:
                [sz1,sz2]=[pars[rr].size(0),1]
            E_grad[rr]=np.zeros([sz1,sz2],dtype=complex)
            gradii[rr]=np.zeros([N_samples,sz1,sz2,len(evals)])
            
        ## Accumulate O_omega1 over lattice sites (also have to see which s were used)
        for ii in range(0, self.L): # loop over lattice sites
            N_samples=s.shape[0]
            vi=outc[:,ii::self.L] 
            psi_i=out[:,ii::self.L]
            si=s[:,ii] # the input/chosen si (what I was missing from prev code/E calc)
            exp_t=np.exp(2*np.real(vi))
            norm_term=np.sum(exp_t,1)
                    
            for kk in range(len(evals)): # have to get the dpsi separately FROM EACH OUTPUT vi

                psi_i[:,kk].mean().backward(retain_graph=True) # mean necessary over samples
                                                    # grad1 will save the per sample grad
                autograd_hacks.compute_grad1(model)
                autograd_hacks.clear_backprops(model) 
                for rr in range(len(pars)):
                    if len(pars[rr].size())==1:
                        gradii[rr][...,kk]=pars[rr].grad1.numpy()[...,None]
                    else:
                        gradii[rr][...,kk]=pars[rr].grad1.numpy()
#                        
            for rr in range(len(pars)): # have to include all pars 
                grad=gradii[rr]
            
                # derivative term (will differ depending on ansatz 'form')
                if self.form.lower()=='exponential':
                    if comp.lower()=='real': dvi = np.einsum('il,ijkl->ijkl', vi, grad)
                    else: dvi = np.einsum('il,ijkl->ijkl', 1j*vi, grad)
                else: raise ValueError('grad for specified form not defined')
        
                st_mult =  np.sum(np.einsum('il,ijkl->ijkl', exp_t, np.real(dvi)),-1)
                sec_term=np.einsum('i,ijk->ijk', 1/norm_term, st_mult)
               
                temp_Ok=np.zeros_like(sec_term,dtype=complex)
                for kk in range(len(evals)): 
                    
                    selection=(si==evals[kk]) # which s were sampled 
                                                #(which indices correspond to the si)
                    sel1=selection*1
                        
                        # For each eval/si, we must select only the subset vi(si) 
                    temp_Ok[:]+=np.einsum('i,ijk->ijk',sel1,dvi[...,kk])
                    
                E_grad[rr] += np.mean(np.einsum('i,ijk->ijk', 2*np.real(E_arg), \
                  np.real(temp_Ok-sec_term)),0)
            
            for rr in range(len(pars)):
                pars[rr].grad=torch.tensor(np.real(E_grad[rr]),dtype=self.dtype).squeeze()
            
        return # E_grad

    '''################### Stochatic Reconfiguation ########################'''

    def SR(self, s, E_loc, lambduh=1):#, cutoff=1e-8): 
        
        E0=np.real(np.mean(E_loc))
        N_samples=s.shape[0]
        
#        if self.autoregressive:
            
        if self.form.lower()=='vector':
            if np.all(self.complex==0): 
                self.complex_out(s)
            m_r=(1/self.complex).squeeze()
            m_i=1j*m_r
        elif self.form.lower()=='euler' or self.form.lower()=='exponential'\
             or self.form.lower()=='real':
            if self.form.lower()=='euler' or self.form.lower()=='real':
                m_r=1/self.real_comp(s).detach().numpy().squeeze()
            else:
                m_r=(np.ones([N_samples,1])).squeeze()
            m_i=(np.ones([N_samples,1])*1j).squeeze()            
            
        E_arg=(np.conj(E_loc)-np.conj(E0))
        
        for ii in range(2):
            if ii==0:# Compute SR for real component
                model=self.real_comp; m=m_r
            else:
                model=self.imag_comp; m=m_i
                
            model.zero_grad()
            
            if not hasattr(model,'autograd_hacks_hooks'):             
                autograd_hacks.add_hooks(model)
            outr=model(s)
            outr.mean().backward()
            autograd_hacks.compute_grad1(model) #computes grad per sample for all samples
            autograd_hacks.clear_backprops(model)
            pars=list(model.parameters())
                
            for param in pars:
                with torch.no_grad():      
                    par_size=param.size() # record original param shape for reshaping
                    Ok=np.einsum("i,ik->ik",m,param.grad1.view([N_samples,-1]).numpy())
                    Exp_Ok=np.mean(Ok,0)[:,None] # gives another axis, necessary for matmul
            #        T1=np.tensordot(np.conj(Ok_list[kk]),Ok_list[kk].T, axes=((0,2),(2,0)))/N_samples
                    T1=np.einsum("kn,mk->nm",np.conj(Ok),Ok.T)/N_samples
                    # These are methods are equivalent! Good sanity check (einsum more versitile)
                    S=2*np.real(T1-np.matmul(np.conj(Exp_Ok),Exp_Ok.T))# the S+c.c. term
                    # folowing same reg/style as senior design matlab code
#                    l_reg=1e-5*np.eye(T1.shape[0],T1.shape[1]) 
                    l_reg=lambduh*np.eye(S.shape[0],S.shape[1])*np.diag(S) # regulation term
#                    l_reg=1e-5*np.diag(np.diag(S)) # regulation term
#                    S=T1-np.matmul(np.conj(Exp_Ok),Exp_Ok.T)+1e-5*np.eye(T1.shape[0],T1.shape[1]) 
                    try:
                        S_inv=np.linalg.inv(S+l_reg+1e-5*np.eye(T1.shape[0],T1.shape[1]))
                    except np.linalg.LinAlgError:
                        print('\n\n S matrix: ', S, '\n\n caused singular value error')
                        raise SystemExit(0)
#                    S[S<cutoff]=0
                    # SVD Inversion alg
#                    [U,D,VT]=np.linalg.svd(S+l_reg)
#                    D=np.diag(1/D) # inverting the D matrix, for SVD, M'=V (D^-1) U.T = (U(D^-1)V.T).T
#                    S_inv=torch.tensor(np.matmul(np.matmul(U,D),VT).T,dtype=self.dtype)
#                    S_inv=torch.tensor(np.linalg.pinv(S+l_reg),dtype=self.dtype) # S^-1 term with reg
                    force=torch.einsum("i,ik->ik",torch.tensor(np.real(2*E_arg*m)\
                    ,dtype=self.dtype),param.grad1.view([N_samples,-1])).mean(0) # force/DE term
                    # Compute SR 'gradient'
                    param.grad=torch.tensor(np.real(np.matmul(S_inv,force[:,None]\
                    .detach().numpy())),dtype=self.dtype).view(par_size).detach() 
#                    param.grad=torch.mm(S_inv,force[:,None]).view(par_size).detach() 
            
            # exits for loop so it is only applied to real comp
            if self.form.lower()=='real':
                break 
            
        return

    '''####### Apply the gradient generated from SR or Grad. Descent ########'''
    ''' Potential improvement- optimization routines for lr (Adam,momentum, pytorch optimizers?)'''
    def apply_grad(self, lr=0.03):
        
        params_r=list(self.real_comp.parameters()) # get the parameters
        if not self.re: params_i=list(self.imag_comp.parameters())    
        
        # apply the Energy gradient descent
#        if len(params_r)==len(params_i) and not self.re:
#            with torch.no_grad():
#                for ii in range(len(params_r)):
#                    params_r[ii] -= lr*params_r[ii].grad 
#                    params_i[ii] -= lr*params_i[ii].grad
#        else:
        with torch.no_grad():
            for param in params_r:
                param -= lr*param.grad
            if not self.re:
                for param in params_i:
                    param -= lr*param.grad
        
        return
    
    ''' #################### SAMPLING METHODS ##########################'''
    
    '''#################### MH Sampling function ############################'''
    def sample_MH(self, N_samples, spin=None, evals=None, s0=None, rot=None):
        # need either the explicit evals or the spin 
        if spin is None and evals is None:
            raise ValueError('Either the eigenvalues of the system or the spin\
                             must be entered')
                
        # var rot: the rule for flipping/rotating a spin between it's eigenvalues
        if rot is None:
            if spin is None:
                dim=len(evals)
            else:
                dim = int(2*spin+1)
            rot =  2*np.pi/dim # assume a rotation that scales with # evals
            # note, can only rotate to 'intermediate/nearby' evals
    
        if evals is None:
            evals=2*np.arange(-spin,spin+1) # +1 is just so s=spin is included
            # times 2 is just the convention that's been used, spin evals of -1,1
        
        if s0 is None:
            s0=np.random.choice(evals,size=self.L)
        
        self.samples=np.zeros([N_samples,self.L])
        self.samples[0,:]=s0
        for n in range(N_samples-1):
            
            pos=np.random.randint(self.L) # position to change
            
            alt_state = self.samples[n,:].copy() # next potential state
            
            if np.random.rand()>=0.5:
                alt_state[pos] = np.real(np.exp(1j*rot)*alt_state[pos]) # flip next random position for spin
            else:
                alt_state[pos] = np.real(np.exp(-1j*rot)*alt_state[pos]) # same chance to flip other direction
            # TODO: will have to generalize to complex evals
            
            # Probabilty of the next state divided by the current
            ln_prob=2*(np.log(np.abs(self.complex_out(torch.tensor(alt_state,dtype=self.dtype))))\
            -np.log(np.abs(self.complex_out(torch.tensor(self.samples[n,:],dtype=self.dtype)))))
            # hopefully reduces potential divide by 0 errors
            prob = np.exp(ln_prob)
#            (np.square(np.abs(self.complex_out(torch.tensor(alt_state,dtype=self.dtype)))))   \
#            /(np.square(np.abs(self.complex_out(torch.tensor(self.samples[n,:],dtype=self.dtype)))))
            
            A = min(1,prob) # Metropolis Hastings acceptance formula

            if A ==1: self.samples[n+1,:]=alt_state
            else: 
                if np.random.rand()<A: self.samples[n+1,:]=alt_state # accepting move with prob A
                else: self.samples[n+1,:] = self.samples[n,:]
            
        return self.samples
    
    '''########## Autoregressive Sampling and Ppsi Gen function ############'''
           
    def QNADE_pass(self, N_samples=None, x=None, grad_required=False): 
                
        if N_samples is None and x is None: 
            raise ValueError('Must enter spin states for Psi calculation or the number of samples to be generated')
        if N_samples is None and x is not None: N_samples, sample = x.shape[0], False
        if N_samples is not None and x is None: sample = True
                
        real_modules = list(self.real_comp.children())
        imag_modules = list(self.imag_comp.children())
                
        for jj in range(len(real_modules)):
            if real_modules[jj].__class__.__name__ in self.supported_layers:
                last_linear_r = jj
        
        for jj in range(len(imag_modules)):
            if imag_modules[jj].__class__.__name__ in self.supported_layers:
                last_linear_i = jj
        
        # a_0, d=0 is set to c (hidden layer bias), and updated on each run. 
        # Expanded to be sample size by L
        a_dr = real_modules[0].bias.expand(N_samples,-1)
        a_di = imag_modules[0].bias.expand(N_samples,-1)
        
        # the full Psi is a product of the conditionals, making a running product easy
        PPSI=np.ones([N_samples],dtype=np.complex128) # if multiplying
        #PPSI=np.zeros([N_samples],dtype=np.complex128)  # if adding logs
        
        # number of outputs we must get for the output layer
        nevals = len(self.evals)
        
        for d in range(self.L):
            
            # This is the hidden/final layer activation
            # rough way to test if it is a layer or an activation
            if not isinstance(real_modules[1], nn.Linear): h_dr, lin_ind_r = real_modules[1](a_dr), 2
            else: h_dr, lin_ind_r = a_dr, 1
            if not isinstance(imag_modules[1], nn.Linear): h_di, lin_ind_i = imag_modules[1](a_di), 2
            else: h_di, lin_ind_i = a_di, 1
            
            # Otherwise, the next module is a linear x-form implying no activation
            # need to ensure the last layer has nevals number of outputs, others are unchanged
            if last_linear_r==lin_ind_r: d1, d2 = nevals*d, nevals*(d+1)  
            else: d1, d2 = 0, len(real_modules[lin_ind_r].bias)
            # initialize the vi_dr (can be x-formed by supplementary layers)
            vi_dr = h_dr.mm(real_modules[lin_ind_r].weight[d1:d2,:].t())\
                    +real_modules[lin_ind_r].bias[d1:d2] 

            if last_linear_i==lin_ind_i: d1, d2 = nevals*d, nevals*(d+1)  
            else: d1, d2 = 0, len(imag_modules[lin_ind_i].bias)
            vi_di = h_di.mm(imag_modules[lin_ind_i].weight[d1:d2,:].t())\
                    +imag_modules[lin_ind_i].bias[d1:d2] 
            
            # TODO: in paper they use conv layers, adding capability to deal with 
            # this layer type could improve performance, also could be a way to 
            # rescale layers as needed (to fit to nevals*L at last layer). 
            # Calculate the x-formation from visible layer to output layer (v_i)
            
            for layer in real_modules[(lin_ind_r+1):len(real_modules)]: 
            # skip first 2 linear layers (used last to update a_d, vi_d above) & activation (used on h_d above)
                if isinstance(layer, nn.Linear):
                    if layer == real_modules[last_linear_r]: d1, d2 = nevals*d, nevals*(d+1)
                    else:  d1, d2 = 0, len(real_modules[lin_ind_r].bias)
                    vi_dr = vi_dr.mm(layer.weight[d1:d2,:].t())+layer.bias[d1:d2] 
                else: vi_dr = layer(vi_dr)
                                 
            for layer in imag_modules[(lin_ind_i+1):len(imag_modules)]: 
                if isinstance(layer, nn.Linear):
                    if layer == imag_modules[last_linear_r]: d1, d2 = nevals*d, nevals*(d+1)
                    else:  d1, d2 = 0, len(imag_modules[lin_ind_i].bias)
                    vi_di = vi_di.mm(layer.weight[d1:d2,:].t())+layer.bias[d1:d2] 
                else: vi_di = layer(vi_di)            
            
            # The Quantum-NADE deviates from a NADE in having a real and imag comp
            # Here we can use both vi to generate a complex vi that is the 
            # basis of our calculations and sampling
            # TODO add form options other than exponential
            vi = np.exp(vi_dr.detach().numpy()+1j*vi_di.detach().numpy())
            
            # TODO create a variable to accumulate the gradients of psi_r (vi_dr)
            # and psi_i (vi_di) (can be used for full grad)
#            if grad_required:
#                    
#                for n in range(N_samples):
#                    for j in range(len(self.evals)):
#                        vi_dr[n,j].backward(retain_graph=True) # takes the mean over the samples
#                        vi_di[n,j].backward(retain_graph=True)
            
            # Normalization and formation of the conditional psi
            exp_vi=np.exp(vi) # unnorm prob of evals 
            norm_const=np.sqrt(np.sum(np.power(np.abs(exp_vi),2),1))
            psi=np.einsum('ij,i->ij', exp_vi, 1/norm_const) 
            
            # Sampling probability is determined by the born rule in QM
            if sample:
                born_psi=np.power(np.abs(psi),2)
                assert np.all(np.sum(born_psi,1)-1<1e-6), "Psi not normalized correctly"
                
                # sampling routine:
                probs = born_psi.copy()
                for ii in range(1, probs.shape[1]): # accumulate prob ranges for easy 
                    probs[:,ii] = probs[:,ii]+probs[:,ii-1] # sampling with 0<alpha<1
                
                a=np.random.rand(N_samples)[:,None]
                samplepos=np.sum(probs<a,1) # find the sample position in eval list
                
                # corrected error where sometimes a too large index occurs here
                # This is a rough fix... But not sure what a better way to ensure it would be
                if np.any(samplepos==len(self.evals)):
                    samplepos[samplepos==len(self.evals)] -= 1 
                
                xd = torch.tensor(self.evals[samplepos], dtype=self.dtype) # sample
                if len(xd.shape)==1:
                    xd = xd[:,None]
                if d==0:
                    samples = xd 
                else:
                    samples = torch.cat((samples,xd),dim=1) 
                # End sampling routine
            
            else:
                xd = x[:,d:d+1]
                if d==0: samples=xd # just checking the iterations
                else: samples = torch.cat((samples,xd),dim=1) 
                
                # find the s_i for psi(s_i), which is to be accumulated for PPSI
                samplepos = (xd==self.evals[1]).int().numpy().squeeze()
                # TODO this definitely won't work for non-binary evals, need to
                # extend functionality to any set of evals
            
            # NADE update rule, uses previously sampled x_d
            a_dr = a_dr + xd.mm(real_modules[0].weight[:,d:(d+1)].t())+real_modules[0].bias
            a_di = a_di + xd.mm(imag_modules[0].weight[:,d:(d+1)].t())+imag_modules[0].bias

            # Multiplicitavely accumulate PPSI based on which sample (s) was sampled
            PPSI=PPSI*psi[range(N_samples),samplepos]
            
            # PPSI may only make sense when inputing an x to get the wvf for...
        
        self.wvf=PPSI
        
        return PPSI, samples
       
        
def kron_matrix_gen(op_list,D,N,bc):
    ''' this function generates a Hamiltonian when it consists of a sum
 of local operators. The local operator should be input at op and the 
 lattice size of the system should be input as N. The
 op can also be entered as the kron product of the two operator 
 matrices or even three with an identity mat in-between for next 
 nearest-neighbor interactions. D is the local Hilbert space size.  '''
    
    import scipy.sparse as sp
    import numpy as np
    
    # extract/convert the operator list to a large operator
    op=op_list[0]
    for ii in range(1,len(op_list)):
        op=np.kron(op,op_list[ii])
    
    sop=sp.coo_matrix(op,dtype=np.float32) # make sparse
    
    matrix=sp.coo_matrix((D**N,D**N),dtype=np.float32) # all 0 sparse 
    
    nops=int(round(np.log(len(op))/np.log(D)) )
    #number of sites the entered op is acting on
    
    bc_term=(nops-1)
    
    for j in range(N-bc_term):
        a=sp.kron(sp.eye(D**j),sop)
        b= sp.kron(a,sp.eye(D**(N-j-nops)))
        matrix=matrix+b
    
    if bc=='periodic':
        for kk in range(nops-1):
            end_ops=op_list[-1]
            for ii in range(kk):
                end_ops=sp.kron(op_list[-ii-2],end_ops)
            
            begin_ops=op_list[0]
            for ii in range(nops-2-kk):
                begin_ops=sp.kron(begin_ops,op_list[ii+1])
            
            a=sp.kron(end_ops,sp.eye(D**(N-nops)))
            b=sp.kron(a,begin_ops)
            matrix=matrix+b
            
    return matrix








# Previously functioning SR and Grad methods (much slower for Psi vector because of loop)
    
#    def energy_gradient(self,s,E_loc,E=None): # add Pytorch optimizer) (fixed lr for now)
#        
#        if E is None:
#            E=np.mean(E_loc)
#        
#        outr = self.real_comp(s).flatten()
#        outi = self.imag_comp(s).flatten()
#        
#        E=np.conj(E)
#        E_loc=np.conj(E_loc)
#        diff=(E_loc-E)
#        mult=torch.tensor(np.real(2*diff),dtype=torch.float)
#        
#        self.real_comp.zero_grad()
#        self.imag_comp.zero_grad()
#        # should be the simpler form to apply dln(Psi)/dw_i
#        if self.form.lower()=='euler':
#            # each form has a slightly different multiplication form
#            (outr.log()*mult).mean().backward()
#            # calling this applies autograd to tensor .grad object i.e. out*mult
#            # which corresponds to dpsi_real(s)/dpars. 
#            # must include the averaging over # samples factor myself 
#            
#            # Angle
#            multiplier = 2*np.imag(-E_loc)
#            multiplier=torch.tensor(multiplier,dtype=torch.float)
#            (multiplier*outi).mean().backward()
#            
#        elif self.form.lower()=='vector':
#            if np.all(self.complex==0): 
#        # could create errors if doesn't use the updated ppsi and new s
#        # but each call of O_local redefines the .complex
#                self.complex_out(s) # define self.complex
#            
#            N_samples=s.size(0)
#            
#            p_r=list(self.real_comp.parameters())
#            p_i=list(self.imag_comp.parameters())   
#            
#            grad_list_r=copy.deepcopy(p_r)
#            grad_list_i=copy.deepcopy(p_i)
#            with torch.no_grad():
#                for param in grad_list_r:
#                    param.copy_(torch.zeros_like(param))
#                    param.requires_grad=False
#                for param in grad_list_i:
#                    param.copy_(torch.zeros_like(param))
#                    param.requires_grad=False
#
#            # what we calculated the gradients should be
#            for n in range(N_samples):
#                
#                self.real_comp.zero_grad() # important so derivatives aren't summed
#                self.imag_comp.zero_grad()    
#                outr[n].backward(retain_graph=True) # retain so that buffers aren't cleared 
#                                                    # and it can be applied again
#                outi[n].backward(retain_graph=True)
#                                                    
#                with torch.no_grad():        
#                    m= ((E_loc[n]-E)/self.complex[n]) 
#                    # [E_l*-E]/Psi according to derivative
#                    m_r=torch.tensor(2*np.real(m) ,dtype=torch.float)
#                    m_i=torch.tensor(2*np.real(1j*m) ,dtype=torch.float)
#                    
#                for kk in range(len(p_r)):
#                    with torch.no_grad():
#                        grad_list_r[kk]+=(p_r[kk].grad)*(m_r/N_samples)
#                for kk in range(len(p_r)):
#                    with torch.no_grad():
#                        grad_list_i[kk]+=(p_i[kk].grad)*(m_i/N_samples)
#            
#            # manually do the mean
#            for kk in range(len(p_r)):
#                p_r[kk].grad=grad_list_r[kk]
#            for kk in range(len(p_i)):
#                p_i[kk].grad=grad_list_i[kk]            
#                        
#        # for testing purposes
##        pr1_grad=params[0].grad
##        pi1_grad=params[0].grad
#            
#        return # pr1_grad, pi1_grad

#    def SR(self,s,E_loc, lambduh=1):
#               
#        E0=np.real(np.mean(E_loc))
#        N_samples=s.size(0)
#        
#        outr=self.real_comp(s)
#        outi=self.imag_comp(s)
#        
#        if self.form=='vector':
#            if np.all(self.complex==0):
#                self.complex_out(s)
#        
#        p_r=list(self.real_comp.parameters())
#        p_i=list(self.imag_comp.parameters())
#        
#        grad_list_i=copy.deepcopy(p_i)
#        with torch.no_grad():
#        
#            for param in grad_list_i:
#                param.copy_(torch.zeros_like(param))
#                param.requires_grad=False
#        # have to make a copy to record the gradient variable Ok and the force DE
#        Ok_list_r=[]
#        Ok_list_i=[]
#        with torch.no_grad():
#            grad_list_r=copy.deepcopy(p_r)
#            for ii in range(len(p_r)):
#                grad_list_r[ii].copy_(torch.zeros_like(p_r[ii]))
#                grad_list_r[ii].requires_grad=False
#                if len(p_r[ii].size())==1:
#                    sz1,sz2=p_r[ii].size(0),1    
#                else:
#                    sz1,sz2=p_r[ii].size()
#                Ok_list_r.append(np.zeros([N_samples,sz1,sz2],dtype=complex))
#                
#            grad_list_i=copy.deepcopy(p_i)
#            for ii in range(len(p_i)):
#                grad_list_i[ii].copy_(torch.zeros_like(p_i[ii]))
#                grad_list_i[ii].requires_grad=False
#                if len(p_i[ii].size())==1:
#                    sz1,sz2=p_i[ii].size(0),1    
#                else:
#                    sz1,sz2=p_i[ii].size()
#                Ok_list_i.append(np.zeros([N_samples,sz1,sz2],dtype=complex))
#                
#        # what we calculated the gradients should be
#        for n in range(N_samples):
#            
#            self.real_comp.zero_grad()
#            self.imag_comp.zero_grad()
#        
#            outr[n].backward(retain_graph=True) # retain so that buffers aren't cleared 
#            outi[n].backward(retain_graph=True)     # and it can be applied again
#            
#            # get the multipliers (Ok=dpsi*m) and the energy gradients for each term
#            if self.form=='vector':
#                m_r=(1/self.complex[n])
#                m_i=1j*m_r
#            else:
#                m_r=1/outr[n].detach().numpy()
#                m_i=1j
#            
#            # term for the force
#            E_arg=(np.conj(E_loc[n])-np.conj(E0))
#                  
#            for kk in range(len(p_r)):
#                with torch.no_grad():
#                    grad_list_r[kk]+=(p_r[kk].grad)*torch.tensor(\
#                    (2*np.real(E_arg*m_r)/N_samples),dtype=torch.float)
#                    Ok=p_r[kk].grad.numpy()*m_r
#                    # to deal with 1-dim params
#                    if len(np.shape(Ok))==1:
#                        Ok=Ok[:,None]
#        #            E_Ok=np.mean(Ok,1)[:,None]
#        #            S=2*np.real(np.matmul(np.conj(Ok),Ok.T)-\
#        #                        np.matmul(np.conj(E_Ok),E_Ok.T))
#                    Ok_list_r[kk][n]=Ok
#        
#            for kk in range(len(p_i)):
#                with torch.no_grad():
#                    grad_list_i[kk]+=(p_i[kk].grad)*torch.tensor(\
#                    (2*np.real(E_arg*m_i)/N_samples),dtype=torch.float)
#                    Ok=p_i[kk].grad.numpy()*m_i
#                    if len(np.shape(Ok))==1:
#                        Ok=Ok[:,None]
#                    Ok_list_i[kk][n]=Ok
#        # unfortunately, must record Ok for each sample so an expectation <Ok> can be taken
#        # This could be a memory/speed issue, but I don't see an obvious route around it
#                    
#        S_list_r=[]
#        for kk in range(len(Ok_list_r)):
#            Exp_Ok=np.mean(Ok_list_r[kk],0)  # conj(mean)=mean(conj)
#        #    T1=np.tensordot(np.conj(Ok_list[kk]),Ok_list[kk].T, axes=((0,2),(2,0)))/N_samples
#            T1=np.einsum('kni,imk->nm',np.conj(Ok_list_r[kk]),Ok_list_r[kk].T)/N_samples
#            # These are methods are equivalent! Good sanity check
#            St=2*np.real(T1-np.matmul(np.conj(Exp_Ok),Exp_Ok.T)) # the S+c.c. term
#            l_reg=lambduh*np.eye(St.shape[0],St.shape[1])*np.diag(St) # regulation term
#            S_list_r.append(St+l_reg) 
#        
#        S_list_i=[]
#        for kk in range(len(Ok_list_i)):
#            Exp_Ok=np.mean(Ok_list_i[kk],0) 
#            T1=np.einsum('kni,imk->nm',np.conj(Ok_list_i[kk]),Ok_list_i[kk].T)/N_samples
#            St=2*np.real(T1-np.matmul(np.conj(Exp_Ok),Exp_Ok.T)) # the S+c.c. term
#            l_reg=lambduh*np.eye(St.shape[0],St.shape[1])*np.diag(St) # regulation term
#            S_list_i.append(St+l_reg) 
#        
#        for kk in range(len(p_r)):
#            S_inv=torch.tensor(np.linalg.pinv(S_list_r[kk]),dtype=torch.float) # have to inverse S
#            if len(grad_list_r[kk].size())==1: # deal with .mm issues when vector Mx1        
#                p_r[kk].grad=(torch.mm(S_inv,grad_list_r[kk][:,None]))\
#                .view(p_r[kk].size()).detach()
#            else:
#                p_r[kk].grad=torch.mm(S_inv,grad_list_r[kk])
#        
#        for kk in range(len(p_i)):
#            S_inv=torch.tensor(np.linalg.pinv(S_list_i[kk]),dtype=torch.float) # have to inverse S
#            if len(grad_list_i[kk].size())==1: # deal with .mm issues when vector Mx1        
#                p_i[kk].grad=(torch.mm(S_inv,grad_list_i[kk][:,None]))\
#                .view(p_i[kk].size()).detach()
#            else:
#                p_i[kk].grad=torch.mm(S_inv,grad_list_i[kk])
#            
#        return 
#
#
#    def energy_gradient(self, s, E_loc, E=None): # add Pytorch optimizer) (fixed lr for now)
#        
#        if E is None:
#            E=np.mean(E_loc)
#                
#        E=np.conj(E)
#        E_loc=np.conj(E_loc)
#        diff=(E_loc-E)
#        
#        self.real_comp.zero_grad()
#        if not self.re: self.imag_comp.zero_grad()
#        # should be the simpler form to apply dln(Psi)/dw_i
#        if self.form.lower()=='real':
#            outr = self.real_comp(s).flatten()
#            mult=torch.tensor(np.real(2*diff),dtype=self.dtype)
#            (outr.log()*mult).mean().backward()
#            
#        elif self.form.lower()=='euler' or self.form.lower()=='exponential':
#            
#            outr = self.real_comp(s).flatten()
#            outi = self.imag_comp(s).flatten()
#            
#            # each form has a slightly different multiplication form
#            # MODULUS
#            mult=torch.tensor(np.real(2*diff),dtype=self.dtype)
#            if self.form.lower()=='euler':
#                assert torch.all(outr>0), "log of 0 or negative number"
#                (outr.log()*mult).mean().backward()
#                
#            elif self.form.lower()=='exponential':
#                (mult*outr).mean().backward() 
#            # calling this applies autograd to tensor .grad object i.e. out*mult
#            # which corresponds to dpsi_real(s)/dpars. 
#            
#            # ANGLE
#            mult = torch.tensor(2*np.imag(-E_loc),dtype=self.dtype)
#            (mult*outi).mean().backward()
#            
#        # Although the speed difference is not significant, the above is still 
#        # faster than using the autograd_hacks per sample gradient version used
#        # for the vector gradients below
#            
#        elif self.form.lower()=='vector':
#            if np.all(self.complex==0): 
#        # could create errors if doesn't use the updated ppsi and new s
#        # but each call of O_local redefines the .complex
#                self.complex_out(s) # define self.complex
#              
#            # hooks accumulate the gradient per sample into layers.backprops_list
#            # only called once otherwise extra grads are accumulated
#            if not hasattr(self.real_comp,'autograd_hacks_hooks'):             
#                autograd_hacks.add_hooks(self.real_comp)
#            if not hasattr(self.imag_comp,'autograd_hacks_hooks'): 
#                autograd_hacks.add_hooks(self.imag_comp)
#            outr=self.real_comp(s)
#            outi=self.imag_comp(s)
#            outr.mean().backward()
#            outi.mean().backward()
#            autograd_hacks.compute_grad1(self.real_comp)
#            autograd_hacks.compute_grad1(self.imag_comp)
#            
#            m=2*(np.conj(E_loc)-np.conj(E))/self.complex.squeeze()
#            
#            p_r=list(self.real_comp.parameters())
#            p_i=list(self.imag_comp.parameters())
#            
#            # multiplying the base per sample grad in param.grad1 by the dPsi
#            # derivative term and assigning to the .grad variable to be applied 
#            # to each parameter variable with the apply_grad function. 
#            for param in p_r:
#                if len(param.size())==2:
#                    ein_str="i,ijk->ijk"
#                elif len(param.size())==1:
#                    ein_str="i,ik->ik"
#                param.grad=torch.einsum(ein_str,torch.tensor(np.real(m)\
#                    ,dtype=self.dtype),param.grad1).mean(0)
#            for param in p_i: # dPsi here is 1j*dPsi of real
#                if len(param.size())==2:
#                    ein_str="i,ijk->ijk"
#                elif len(param.size())==1:
#                    ein_str="i,ik->ik"
#                param.grad=torch.einsum(ein_str,torch.tensor(np.real(1j*m)\
#                    ,dtype=self.dtype),param.grad1).mean(0)
#          
#            # clear backprops_list for next run
#            autograd_hacks.clear_backprops(self.real_comp)
#            autograd_hacks.clear_backprops(self.imag_comp)
#            
#        return 
    


    # Begin the autoregressive sampling and Psi forward pass routine 
#    def Autoregressive_pass(self,s,evals):
#        
#        outc=self.complex_out(s) # the complex output given an ansatz form  
#        new_s=torch.zeros_like(s)
#        
#        if len(s.shape)==2:
#            [N_samples,L]=s.shape
#            nout=outc.shape[1]
#        else:
#            [N_samples,L]=1,s.shape[0]
#            nout=outc.shape[0]
#            outc, new_s=outc[None,:], new_s[None,:] # extra dim for calcs
#        
#        nevals=len(evals)
#        
#        # Making sure it is an autoregressive model
#        assert nout%L==0,"(Output dim)!=int*(Input dim), not an Autoregressive NN"
#                
#        # the full Psi is a product of the conditionals, making a running product easy
#        self.wvf=np.ones([N_samples],dtype=np.complex128) 
#        
#        if self.dtype==torch.double: prec=5e-15
#        else: prec=5e-7
#        
#        for ii in range(0, L): # loop over lattice sites
#            
#            si=s[:,ii] # the input/chosen si (maybe what I'm missing from prev code/E calc)
#            # normalized probability/wavefunction
#            vi=outc[:,ii::L] 
#            # The MADE is prob0 for 0-nin outputs and then prob1 for 
#            # nin-2nin outputs, etc. until ((nevals-1)-nevals)*nin outputs 
#            tester=np.arange(0,nout);  # print(tester[ii:nlim:L]) # to see slices 
#            assert len(tester[ii::L])==nevals, "Network Output missing in calculation"
#            
#            exp_vi=np.exp(vi) # unnorm prob of evals 
#            norm_const=np.sqrt(np.sum(np.power(np.abs(exp_vi),2),1))
#            psi=np.einsum('ij,i->ij', exp_vi, 1/norm_const) # love this tool
#            
#            born_psi=np.power(np.abs(psi),2)
#            
#            # satisfy the normalization condition?
##            assert np.all(np.sum(born_psi,1)-1<1e-6), "Psi not normalized correctly"
#        
#            # Now let's sample from the binary distribution
#            rands=np.random.rand(N_samples)
#            
#            psi_s=np.zeros(N_samples, complex) # needed to accumulate Ppsi
#            checker=np.zeros(N_samples)
#            for jj in range(nevals): 
#                        
#                prev_selection=(si.numpy()==evals[jj]) # which s were sampled 
#                # psi(s), accumulate psi for the s that were used to gen samples
#                psi_s+=prev_selection*1*psi[:,jj]
#                
#                # sampling if a<born_psi, sample
#                selection=((0<=rands)*(rands-born_psi[:,jj]<=prec)) 
#                # Due to precision have to use <=1e-7 as errors will occur
#                # when comparing differences of order 1e-8. (see below check)
#                checker+=selection*1
#                
#                new_s[selection,ii]=evals[jj]
#        
#                rands=rands-born_psi[:,jj] # shifting the rands for the next sampling
#            
#            if not np.all(checker)==1: 
#                prob_ind=np.where(checker==0)
#                raise ValueError("N_samples were not sampled. error at: \n", \
#                    prob_ind, '\n with random array: \n', rands[prob_ind],\
#                    '\n and probability array: \n', born_psi[prob_ind,:])
#            
##            assert np.all(checker)==1, "N_samples were not sampled"
#            
#            # Accumulating Ppsi, which is psi_1(s)*psi_2(s)...*psi_L(s)
#            self.wvf=self.wvf*psi_s
#        
#        return new_s  


