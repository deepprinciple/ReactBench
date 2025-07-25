"""
This module contains the find_lewis() function and associated helper functions to find the 
best resonance structures for yarpecules.
"""

import sys
import itertools
import numpy as np
from copy import copy,deepcopy

from ReactBench.utils.taffi_functions import adjmat_to_adjlist,return_rings,graph_seps
from ReactBench.utils.properties import el_valence,el_n_deficient,el_expand_octet,el_en,el_pol,el_n_expand_octet,el_metals





def bmat_hash(bond_mat):
    """ 
    Creates a unique hash value for each bond-electron matrix that is used to speed uniqueness checks.
    
    Parameters
    ----------
    bond_mat : array
               The bond electron matrix that the hash is calculated for.
    
    Returns
    -------
    hash_value: float
    

    Notes
    -----            
    The hash is calculated as bond_mat * an ascending array (1,2,... counting up through all elements and rows) summed over rows, 
    then those values are multiplied by 10**(-i/100) where i is the column, and summed.
    """
    return np.sum([ _*10**(-(count/100)) for count,_ in enumerate(np.sum(bond_mat*np.arange(1,len(bond_mat)**2+1).reshape(len(bond_mat),len(bond_mat)),axis=0)) ])            


def find_lewis(elements,adj_mat,q=0,rings=None,mats_max=10,mats_thresh=10.0,w_def=-2,w_exp=0.1,w_formal=0.1,w_aro=-10,w_rad=0.1,w_zwitter=0.1,w_ionic=5.0,local_opt=True):

    """ 
    Algorithm for finding relevant Lewis Structures of a molecular graph given an overall charge.
    
    Parameters
    ----------
    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix. 
               Expects a list of lower-case elemental symbols.
        
    adj_mat  : array of integers
               Contains the bonding information of the molecule of interest, indexed to the elements list.

    q : int, default=0
        Sets the overall charge for the molecule. 
    
    rings: list, default=None
           List of lists holding the atom indices in each ring. If none, then the rings are calculated.

    mats_max: int, default=10
              The maximum number of bond electron matrices to return. 
    
    mats_thresh: float, default=0.5
                 The value used to determine if a bond electron matrix is worth returning to the user. Any matrix with a score within this value of the minimum structure will be returned as a potentially relevant resonance structure (up to mats_max).

    w_def: float, default=-1
           The weight of the electron deficiency term in the objective function for scoring bond-electron matrices.

    w_exp: float, default=0.1
           The weight of the term for penalizing octet expansions in the objective function for scoring bond-electon matrices.

    w_formal: float, default=0.1
              The weight of the formal charge term in the objective function for scoring bond-electon matrices.

    w_aro: float, default=-24
           The weight of the aromatic term in the objective function for scoring bond-electron matrices.

    w_rad: float, default=0.1
           The weight of the radical term in the objective function for scoring bond-electron matrices.

    local_opt: boolean, default=True
               This controls whether non-local charge transfers are allowed (False). This can be expensive. 

    Returns
    -------
    bond_mats : list
                A list of arrays containing up to `mats_max` bond-electron matrices. Sorted by score in ascending order (lower is better).

    scores: list
            A list of scores for each bond-electon matrix within bond_mats.
        
    """
    old_rec_limit =sys.getrecursionlimit()
    sys.setrecursionlimit(5000)            

    # Array of atom-wise octet requirements for determining electron deficiencies
    e_def = np.array([ el_n_deficient[_] for _ in elements ])

    # Array of atom-wise octet requirements for determining expanded octects 
    e_exp = np.array([ el_n_expand_octet[_] for _ in elements ])

    # Generate rings if they weren't supplied. Needed to determine allowed double bonds in rings and resonance
    if not rings: rings = return_rings(adjmat_to_adjlist(adj_mat),max_size=10,remove_fused=True)

    # Get the indices of atoms in rings < 10 (used to determine if multiple double bonds and alkynes are allowed on an atom)
    ring_atoms = { j for i in [ _ for _ in rings if len(_) < 10 ] for j in i }

    # Get the indices of bridgehead atoms whose largest parent ring is smaller than 8 (i.e., Bredt's rule says no double-bond can form at such bridgeheads)
    bredt_rings = [ set(_) for _ in rings if len(_) < 8 ]
    bridgeheads = []
    if len(bredt_rings) > 2:
        for r in itertools.combinations(bredt_rings,3):
            bridgeheads += list(r[0].intersection(r[1].intersection(r[2]))) # bridgeheads are atoms in at least three rings. 
    bridgeheads = set(bridgeheads)

    # Get the graph separations if local_opt = True
    if local_opt:
        seps = graph_seps(adj_mat)
    # using seps=0 is equivalent to allowing all charge transfers (i.e., all atoms are treated as nearby)
    else:
        seps = np.zeros([len(elements),len(elements)])

    # Initialize lists to hold bond_mats and scores
    bond_mats = []
    scores = []
    hashes = set([])
    
    # Initialize score function for ranking bond_mats
    en = np.array([ el_en[_] for _ in elements ]) # base electronegativities of each atom
    rad_env = np.array([ el_en[_] for _ in elements ]) # base electronegativities of each atom

    factor = 0.0
    
    obj_fun = lambda x: bmat_score(x,elements,rings,cat_en=en,an_en=en,rad_env=np.zeros(len(elements)),e_def=e_def,e_exp=e_exp,w_def=w_def,\
                                   w_exp=w_exp,w_formal=w_formal,w_aro=0,w_rad=w_rad,w_zwitter=w_zwitter,w_ionic=w_ionic,factor=factor,verbose=False) # aro term is turned off initially since it traps greedy optimization
    
    # Find the minimum bmat structure
    # gen_init() generates a series of initial guesses. For neutral molecules, this guess is singular. For charged molecules, it will yield all possible charge placements (expensive but safe).
    count = 0
    for score,bond_mat,reactive in gen_init(obj_fun,adj_mat,elements,rings,q):
        count += 1
        if bmat_unique(bond_mat,bond_mats):
            scores += [score]
            bond_mats += [bond_mat]
            hashes.add(bmat_hash(bond_mat))
            bond_mats,scores,_,_,_ = gen_all_lstructs(obj_fun,bond_mats,scores,hashes,elements,reactive,rings,ring_atoms,bridgeheads,seps=np.zeros([len(elements),len(elements)]), min_score=scores[0], ind=len(bond_mats)-1,N_score=1000,N_max=10000,min_win=100.0,min_opt=True)
    # Update objective function to include (anti)aromaticity considerations and update scores of the current bmats
    obj_fun = lambda x: bmat_score(x,elements,rings,cat_en=en,an_en=en,rad_env=np.zeros(len(elements)),e_def=e_def,e_exp=e_exp,w_def=w_def,w_exp=w_exp,w_formal=w_formal,\
                                   w_aro=w_aro,w_rad=w_rad,w_zwitter=w_zwitter,w_ionic=w_ionic,factor=factor,verbose=False)                        
    scores = [ obj_fun(_) for _ in bond_mats ]            
            
    # Sort by initial scores
    bond_mats = [ _[1] for _ in sorted(zip(scores,bond_mats),key=lambda x:x[0]) ]
    scores = sorted(scores)
    
    # Generate resonance structures: Run starting from the minimum structure and allow moves that are within s_window of the min_enegy score
    bond_mats=[bond_mats[0]]    
    scores = [scores[0]]
    hashes = set([bmat_hash(bond_mats[0])])
    bond_mats,scores,hashes,_,_ = gen_all_lstructs(obj_fun,bond_mats, scores, hashes, elements, reactive, rings, ring_atoms, bridgeheads, seps, min_score=min(scores), ind=len(bond_mats)-1,N_score=1000,N_max=10000,min_opt=True)
    
    # Sort by initial scores
    inds = np.argsort(scores)
    bond_mats = [ bond_mats[_] for _ in inds ]
    scores = [ scores[_] for _ in inds ]
    
    # Keep all bond-electron matrices within mats_thresh of the minimum but not more than mats_max total
    flag = True
    for count,i in enumerate(scores):
        if count > mats_max-1:
            flag = False
            break
        if i - scores[0] < mats_thresh:
            continue
        else:
            flag = False
            break
    if flag:
        count += 1
    # Shed the excess b_mats
    bond_mats = bond_mats[:count]
    scores = scores[:count]

    # Calculate the number of charge centers bonded to each atom (determines hybridization)
    # calculated as: number of bonded_atoms + number of unbound electron orbitals (pairs or radicals).
    # The latter is calculated as the minimum value over all relevant bond_mats (e.g., ester oxygen, R-O(C=O)-R will only have one lone pair not two in this calculation)
    centers = [ i+np.ceil(min([ b[count,count] for b in bond_mats ])*0.5) for count,i in enumerate(sum(adj_mat)) ] # finds the number of charge centers bonded to each atom (determines hybridization) 
    s_char = np.array([ 1/(_+0.0001) for _ in centers ]) # need s-character to assign positions of anions for precisely
    pol = np.array([ el_pol[_] for _ in elements ]) # polarizability of each atom

    # Calculate final scores. For finding the preferred position of formal charges, some small corrections are made to the electronegativities of anion and cations based on neighboring atoms and hybridization.
    # The scores of ions are also adjusted by their ionization/reduction energy to provide a 0-baseline for all species regardless of charge state.
    rad_env = -np.sum(adj_mat*(0.1*pol/(100+pol)),axis=1)
    bond_mats = adjust_metals(bond_mats,adj_mat,elements)
    scores = [ bmat_score(_,elements,rings,en,en,rad_env,e_def,e_exp,w_def=w_def,w_exp=w_exp,w_formal=w_formal,w_aro=w_aro,w_rad=w_rad,\
                          w_zwitter=w_zwitter,w_ionic=w_ionic,factor=factor,verbose=False) for _ in bond_mats ]
        
    # Sort by final scores
    inds = np.argsort(scores)
    bond_mats = [ bond_mats[_] for _ in inds ]
    scores = [ scores[_] for _ in inds ]
    sys.setrecursionlimit(old_rec_limit)
    return bond_mats,scores

class LewisStructureError(Exception):

    def __init__(self, message="An error occured in a find_lewis() call."):
        self.message = message
        super().__init__(self.message)      
        
def gen_init(obj_fun,adj_mat,elements,rings,q):

    """ 
    A helper-generator for initial guesses for the final_lewis algorithm.
    
    Parameters
    ----------
    obj_fun : function
              A function that accepts a bond electron matrix and returns a score. This assumes that the elements and objective function weights have already been supplied (e.g., by defining an anonymous function to pass to this function). 
    
    adj_mat  : array of integers
               Contains the bonding information of the molecule of interest, indexed to the elements list.

    elements : list of lower-case elemental symbols
               Contains elemental information indexed to the supplied adjacency matrix.
    
    rings: list, 
           List of lists holding the atom indices in each ring. 

    q : int
        Sets the overall charge for the molecule. 

    Yields
    -------
    iterator: tuple
              This function yields all a set of initial guesses for the find_lewis algorithm via iteration. Each iteration returns a tuple (score, bmat, inds) 
              containing the score of the initial guess, the bond-electron matrix, and the list of reactive indices.
    """
    
    # Array of atom-wise electroneutral electron expectations for convenience.
    eneutral = np.array([ el_valence[_] for _ in elements ])    

    # Array of atom-wise octet requirements for determining electron deficiencies
    e_def = np.array([ el_n_deficient[_] for _ in elements ])

    # Array of atom-wise octet requirements for determining expanded octects 
    e_exp = np.array([ el_n_expand_octet[_] for _ in elements ])
    
    # Initial neutral bond electron matrix with sigma bonds in place
    bond_mat = deepcopy(adj_mat) + np.diag(np.array([ _ - sum(adj_mat[count]) for count,_ in enumerate(eneutral) ]))

    # Correct metal atoms (remove formed bonds)
    bond_mat_tmp = deepcopy(bond_mat)
    corrs = []
    for count_i,i in enumerate(elements):
        if i in el_metals:
            for count_j,j in enumerate(bond_mat[count_i]):
                if count_i != count_j and j > 0:
                    bond_mat_tmp[count_i,count_j] += -1
                    bond_mat_tmp[count_j,count_i] += -1
                    bond_mat_tmp[count_i,count_i] += 1
                    bond_mat_tmp[count_j,count_j] += 1                    
                    corrs += [(-1,count_i,count_j),(-1,count_j,count_i),(1,count_i,count_i),(1,count_j,count_j)]
    bond_mat = bond_mat_tmp

    # Correct atoms with negative charge using q (if anions)
    qeff = q        
    n_ind = [ _ for _ in range(len(bond_mat)) if bond_mat[_,_] < 0 ]
    while (len(n_ind)>0 and qeff<0):
        bond_mat[n_ind[0],n_ind[0]] += 1
        qeff += 1
        n_ind = [ _ for _ in range(len(bond_mat)) if bond_mat[_,_] < 0 ]        

    # Correct atoms with negative charge using lone electrons
    n_ind = [ _ for _ in range(len(bond_mat)) if bond_mat[_,_] < 0 ]
    l_ind = [ _ for _ in range(len(bond_mat)) if bond_mat[_,_] > 0 ] 
    while (len(n_ind)>0 and len(l_ind)>0):
        for i in l_ind:
            try:
                def_atom = n_ind.pop(0)                
                bond_mat[def_atom,def_atom] += 1
                bond_mat[i,i] -= 1
            except:
                continue
        n_ind = [ _ for _ in range(len(bond_mat)) if bond_mat[_,_] < 0 ]
        l_ind = [ _ for _ in range(len(bond_mat)) if bond_mat[_,_] > 0 ] 

    # Raise error if there are still negative charges on the diagonal
    if len([ _ for _ in range(len(bond_mat)) if bond_mat[_,_] < 0 ]):
        raise LewisStructureError("Incompatible charge state and adjacency matrix.")

    # Correct expanded octets if possible (while performs CT from atoms with expanded octets
    # to deficient atoms until there are no more expanded octets or no more deficient atoms)
    e_ind = [ count for count,_ in enumerate(return_expanded(bond_mat,elements,e_exp)) if _ > 0 and bond_mat[count,count] > 0 ]
    d_ind = [ count for count,_ in enumerate(return_def(bond_mat,elements,e_def)) if _ < 0 ]    
    while (len(e_ind)>0 and len(d_ind)>0):
        for i in e_ind:
            try:
                def_atom = d_ind.pop(0)                
                bond_mat[def_atom,def_atom] += 1
                bond_mat[i,i] -= 1
            except:
                continue
        e_ind = [ count for count,_ in enumerate(return_expanded(bond_mat,elements,e_exp)) if _ > 0 and bond_mat[count,count] > 0 ]
        d_ind = [ count for count,_ in enumerate(return_def(bond_mat,elements,e_def)) if _ < 0 ]    
    
    # Get the indices of atoms in rings < 10 (used to determine if multiple double bonds and alkynes are allowed on an atom)
    ring_atoms = { j for i in [ _ for _ in rings if len(_) < 10 ] for j in i }

    # If charge is being added, then try all combinations that don't violate octet limits
    if qeff<0:

        # Check the valency of the atoms to determine which can accept a charge
        e = return_e(bond_mat)
        heavies = [ count for count,_ in enumerate(elements) if e[count] < el_n_deficient[_] or el_expand_octet[_] ]

        # Loop over all q-combinations of heavy atoms
        for i in itertools.combinations_with_replacement(heavies, int(abs(qeff))):

            # Create a fresh copy of the initial be_mat and add charges
            tmp = copy(bond_mat)
            for _ in i: tmp[_,_] += 1

            # Find reactive atoms (i.e., atoms with unbound electron(s) or deficient atoms or a formal charge)
            e = return_e(tmp)
            f = return_formals(tmp,elements)
            reactive = [ count for count,_ in enumerate(elements) if ( tmp[count,count] or e[count] < el_n_deficient[_] or f[count] != 0 ) ]
            
            # Form bonded structure
            for j in reactive:
                while valid_bonds(j,tmp,elements,reactive,ring_atoms):            
                    for k in valid_bonds(j,tmp,elements,reactive,ring_atoms): tmp[k[1],k[2]]+=k[0]
            
            yield obj_fun(tmp),tmp, reactive

    # If charge is being removed, then remove from the least electronegative atoms first
    elif qeff>0:

        # Atoms with unbound electrons
        lonelies = [ count for count,_ in enumerate(bond_mat) if bond_mat[count,count] > 0 ]

        # Loop over all q-combinations of atoms with unbound electrons to be oxidized
        for i in itertools.combinations_with_replacement(lonelies, qeff):

            # This construction is used to handle cases with q>1 to avoid taking more electrons than are available.
            tmp = copy(bond_mat)
            
            flag = True
            for j in i:
                if tmp[j,j] > 0:
                    tmp[j,j] -= 1
                else:
                    flag = False
            if not flag:
                continue

            # Find reactive atoms (i.e., atoms with unbound electron(s) or deficient atoms or a formal charge)
            e = return_e(tmp)
            f = return_formals(tmp,elements)
            reactive = [ count for count,_ in enumerate(elements) if ( tmp[count,count] or e[count] < el_n_deficient[_] or f[count] != 0 ) ]
            
            # Form bonded structure
            for j in reactive:
                while valid_bonds(j,tmp,elements,reactive,ring_atoms):            
                    for k in valid_bonds(j,tmp,elements,reactive,ring_atoms): tmp[k[1],k[2]]+=k[0]

            yield obj_fun(tmp),tmp,reactive
        
    else:

        # Find reactive atoms (i.e., atoms with unbound electron(s) or deficient atoms or a formal charge)
        e = return_e(bond_mat)
        f = return_formals(bond_mat,elements)
        reactive = [ count for count,_ in enumerate(elements) if ( bond_mat[count,count] or e[count] < el_n_deficient[_] or f[count] != 0 ) and ( _ not in el_metals ) ]
        # Form bonded structure
        for j in reactive:
            while valid_bonds(j,bond_mat,elements,reactive,ring_atoms):            
                for k in valid_bonds(j,bond_mat,elements,reactive,ring_atoms): bond_mat[k[1],k[2]]+=k[0]

        yield obj_fun(bond_mat),bond_mat,reactive

def gen_all_lstructs(obj_fun, bond_mats, scores, hashes, elements, reactive, rings, ring_atoms, bridgeheads, seps, min_score, ind=0, counter=100, N_score=1000, N_max=10000, min_opt=False, min_win=False):

    """ 
    A generator for find_lewis() that recursively applies a set of valid bond-electron moves to find all relevant resonance structures. 
    
    Parameters
    ----------
    obj_fun : function
              A function that accepts a bond electron matrix and returns a score. This assumes that the elements and objective function weights have already been supplied (e.g., by defining an anonymous function to pass to this function). 
    
    bond_mats  : list of bond_mat arrays 
               Contains the bond-electron matrices that have already been discovered and scored. Used by the algorithm to avoid back-tracking. 

    scores : list of floats
             Contains the scores for all  bond-electron matrices that have been enumerated.
    
    hashes : set of floats
             Contains a set of bond-electron matrix  hash values used to accelerate the check for duplication. 

    elements : list of lower-case elemental symbols
               Contains elemental information indexed to the supplied adjacency matrix.

    reactive: list of integers
              Contains the indices of the atoms in the bond-electron matrix that are candidates for the rearrangement moves.

    rings: list
           List of lists holding the atom indices in each ring. 

    ring_atoms: list of integers
                Contains the indices of of atoms in rings. These are used to determine the possibility of forming double bonds if multiple double bonds and alkynes are allowed on an atom when enumerating resonance structures.

    bridgeheads: list of integers
                 Contains the indices of the atoms serving as ring bridgeheads. These are used to determine enforce Bredt's rules during the resonance structure search. 

    seps: array
          Contains the number of bonds separating each pair of atoms at the ij-th position.

    min_score: float
               Contains the current best score out of all enumerated lewis structures. 

    ind: int, default=0
         Contains the index of the bond_mat within bond_mats that the function is supposed to act on.

    counter: int, default=0 
             Keeps track of the number of iterations that have passed without finding a better lewis structure. Used to determine the `N_score` break condition.

    N_score: int, default=100
             The function will break if this number of steps pass without finding an improved Lewis Structure. 

    N_max: int, default=10000
           The function will break if this number of bond electron matrices have been generated. 

    min_opt: boolean, default=False
             If set to `True` then the search is run in a greedy mode where Lewis Structures are only accepted if they are as good or better than the structure discovered up to that point. This option is used as part of the base algortihm to initially find a reasonable structure before a more fine-grained comprehensive search. 

    min_win: float, default=False
             When set, a Lewis Structure is only accepted if its score is within this value of the best structure found up to that point. This allows the algorithm to explore intermediate structures that may be less ideal but that eventually lead to an overall relaxation of the structure.  

    Yields
    -------
    iterator: tuple
              This function yields all a set of initial guesses for the find_lewis algorithm via iteration. Each iteration returns a tuple, (score, bond_mat, reactive_indices),
               containing the score of the initial guess, the bond-electron matrix, and the list of reactive indices.

    """
    
    # Loop over all possible moves, recursively calling this function to account for the order dependence. 
    # This could get very expensive very quickly, but with a well-curated moveset things are still very quick for most tested chemistries. 
    for ind in range(0, len(bond_mats)):
        for j in valid_moves(bond_mats[ind],elements,reactive,rings,ring_atoms,bridgeheads,seps):

            # Carry out moves on trial bond_mat
            tmp = copy(bond_mats[ind])        
            for k in j: tmp[k[1],k[2]]+=k[0]

            # calc objective function and hash value
            score = obj_fun(tmp)
            b_hash = bmat_hash(tmp)    
        
            # Check if a new best Lewis structure has been found, if so, then reset counter and record new best score
            if score <= min_score:
                counter = 0
                min_score = score
            else:
                counter += 1

            # Break if too long (> N_score) has passed without finding a better Lewis structure
            if counter >= N_score:
                return bond_mats,scores,hashes,min_score,counter

            # If min_opt=True then the search is run in a greedy mode where only moves that reduce the score are accepted
            if min_opt:

                if counter == 0:
                    # Check that the resulting bond_mat is not already in the existing bond_mats
                    if b_hash not in hashes: 
                        bond_mats += [tmp]
                        scores += [score]
                        hashes.add(b_hash)

                        # Recursively call this function with the updated bond_mat resulting from this iteration's move. 
                        bond_mats,scores,hashes,min_score,counter = gen_all_lstructs(obj_fun,bond_mats,scores,hashes,elements,reactive,rings,ring_atoms,bridgeheads,seps,\
                                                                              min_score,ind=len(bond_mats)-1,counter=counter,N_score=N_score,N_max=N_max,min_opt=min_opt,min_win=min_win)

            else:
                # min_win option allows the search to follow structures that increase the score up to min_win above the score of the best structure
                if min_win:
                    if (score-min_score) < min_win:

                        # Check that the resulting bond_mat is not already in the existing bond_mats
                        if b_hash not in hashes: 
                            bond_mats += [tmp]
                            scores += [score]
                            hashes.add(b_hash)
                        
                            # Recursively call this function with the updated bond_mat resulting from this iteration's move. 
                            bond_mats,scores,hashes,min_score,counter = gen_all_lstructs(obj_fun,bond_mats,scores,hashes,elements,reactive,rings,ring_atoms,bridgeheads,seps,\
                                                                                  min_score,ind=len(bond_mats)-1,counter=counter,N_score=N_score,N_max=N_max,min_opt=min_opt,min_win=min_win)

                # otherwise all structures are recursively explored (can be very expensive)
                else:

                    # Check that the resulting bond_mat is not already in the existing bond_mats
                    if b_hash not in hashes:
                    
                        bond_mats += [tmp]
                        scores += [score]
                        hashes.add(b_hash)

                        # Recursively call this function with the updated bond_mat resulting from this iteration's move. 
                        bond_mats,scores,hashes,min_score,counter = gen_all_lstructs(obj_fun,bond_mats,scores,hashes,elements,reactive,rings,ring_atoms,bridgeheads,seps,\
                                                                              min_score,ind=len(bond_mats)-1,counter=counter,N_score=N_score,N_max=N_max,min_opt=min_opt,min_win=min_win)
                    
            # Break if max has been encountered.
            if len(bond_mats) > N_max:
                return bond_mats,scores,hashes,min_score,counter
    
    return bond_mats,scores,hashes,min_score,counter
    
def bmat_unique(new_bond_mat,old_bond_mats):
    """
    Helper function for `gen_all_lstructs()` that checks whether an array already exists in a set of arrays. 
    Deprecated because it was expensive. Now a hash is used in place of this in the comparison routine.
    """
    for i in old_bond_mats:
        if all_zeros(i-new_bond_mat):
            return False
    return True 

# Helper function for bmat_unique that checks is a numpy array is all zeroes (uses short-circuit logic to speed things up in contrast to np.any)
def all_zeros(m):
    """
    Helper function for `bmat_unique()` that checks is a numpy array is all zeroes (uses short-circuit logic to speed things up in contrast to np.any) 
    """
    for _ in m.flat:
        if _:
            return False # short-circuit logic at first non-zero
    return True

def valid_moves(bond_mat,elements,reactive,rings,ring_atoms,bridgeheads,seps):
    """ 
    Generator that returns all valid moves that can be performed on a given bond-electron matrix. 
    Used as a helper function for gen_all_lstructs to loop over potential lewis structures.
    
    Parameters
    ----------
    bond_mat : array
               The bond electron matrix that the bond/electron rearrangments are calculated for. 

    elements : list
               list of elements indexed to the bond_mat

    reactive : list
               List of integers corresponding to the indices of bond_mat where atoms capable of undergoing bond-elctron rearrangments reside. 

    rings: list, 
           List of lists holding the atom indices in each ring. Used to determine (anti) aromaticity.

    ring_atoms: list
                List of integers corresponding to the indices of bond_mat where the atoms reside in a ring. Used to avoid forming allenes and alkynes within rings. 

    bridgeheads: list
                 List of integers corresponding to the indices of bond_mat where the atoms reside at bridgeheads. Used for respecting Bredt's rule. 

    seps: array
          Array holding the graphical separations of each pair of atoms. Used to determine valid charge transfers based on proximity.

    Yields
    ------
    move: list of tuples,

          Each tuple in the list is composed of (int, i, j) where int is the value to be added to the ij position of the bond-electron matrix.

    Notes
    -----            
    Attempted moves on each reactive atom (i) include (in this order): 
    (1) shifting a pi-bond between a neighbor (j) and next-nearest neighbor (k) of a 2-electron deficient atom (i) to one between i and j.     
    (2) shifting a pi-bond between a neighbor (j) and next-nearest neighbor (k) of a radical 1-electron deficient atom (i) to one between i an j.
    (3) shifting a pi-bond between a neighbor (j) and next-nearest neighbor (k) of a lone-pair containing atom (i) to a lone-pair on k and a new pi-bond between i and j.
    (4) forming a pi-bond between a radical containing atom (i) and a neighbor (j) with unbound electron(s). This might be accompanied by a charge transfer from j to another atom if required. 
    (5) forming a pi-bond between an atom with a long pair (i) and a neighbor (j) capable of accepting a pi-bond. 
    (6) turn a pi-bond between i and its neighbor j into a lone pair on i if favored by electronegativity or aromaticity.
    (7) transfer an electron to i from its neighbor j, if i is electron deficient and has a greater electronegativity.
    (8) transfer a charge from i to another atom if i has an expanded octet and unbound electrons. 
    (9) shuffle aromatic and anti-aromatic bonds (i.e., change bond alteration along the cycle). 
    (10) forming a pi-bond between two radicals
    All of these moves are contingent on the ability of atoms to expand octet, whether they are electron deficient, and whether the move would lead to unphysical ring-strain. 

    """    
    e = return_e(bond_mat) # current number of electrons associated with each atom

    # Loop over the individual atoms and determine the moves that apply
    for i in reactive:

        # All of these moves involve forming a double bond with the i atom. Constraints that are common to all of the moves are checked here.
        # These are avoiding forming alkynes/allenes in rings and Bredt's rule (forming double-bonds at bridgeheads)
        if i not in bridgeheads and ( i not in ring_atoms or sum([ _ for count,_ in enumerate(bond_mat[i]) if count != i and _ > 1 ]) == 0 ):

            # Move 1: i is electron deficient and has an adjacent pi-bond between neighbor and next-nearest neighbor atoms, j and k, then the j-k pi-bond is turned into a new i-j pi-bond.
            if e[i]+2 <= el_n_deficient[elements[i]] or el_expand_octet[elements[i]]:
                for j in return_connections(i,bond_mat,inds=reactive):
                    for k in [ _ for _ in return_connections(j,bond_mat,inds=reactive,min_order=2) if _ != i ]:
                        yield [(1,i,j),(1,j,i),(-1,j,k),(-1,k,j)]

            # Move 2: i has a radical and has an adjacent pi-bond between neighbor and next-nearest neighbor atoms, j and k, then the j-k pi-bond is homolytically broken and a new pi-bond is formed between i and j
            if bond_mat[i,i] % 2 != 0 and e[i] < el_n_deficient[elements[i]]:
                for j in return_connections(i,bond_mat,inds=reactive):
                    for k in [ _ for _ in return_connections(j,bond_mat,inds=reactive,min_order=2) if _ != i ]:
                        yield [(1,i,j),(1,j,i),(-1,j,k),(-1,k,j),(-1,i,i),(1,k,k)]

            # Move 3: i has a lone pair and has an adjacent pi-bond between neighbor and next-nearest neighbor atoms, j and k, then the j-k pi-bond is heterolytically broken to form a lone pair on k and a new pi-bond is formed between i and j
            if bond_mat[i,i] >= 2:
                for j in return_connections(i,bond_mat,inds=reactive):
                    for k in [ _ for _ in return_connections(j,bond_mat,inds=reactive,min_order=2) if _ != i ]:
                        yield [(1,i,j),(1,j,i),(-1,j,k),(-1,k,j),(-2,i,i),(2,k,k)]

            if bond_mat[i, i]%2!=0:
                for j in return_connections(i, bond_mat, inds=reactive):
                    if bond_mat[j, j]%2!=0:
                        for k in [ _ for _ in return_connections(j,bond_mat,inds=reactive,min_order=2) if _ != i ]:
                            yield [(-1, i, i), (-1, j, j), (1, i, j), (1, j, i)]
            # Move 4: i has a radical and a neighbor with unbound electrons, form a bond between i and the neighbor
            if bond_mat[i,i] % 2 != 0 and ( el_expand_octet[elements[i]] or e[i] < el_n_deficient[elements[i]] ):

                # Check on connected atoms
                for j in return_connections(i,bond_mat,inds=reactive):

                    # Electron available @j
                    if bond_mat[j,j] > 0:

                        # Straightforward homogeneous bond formation if j is deficient or can expand octet
                        if ( el_expand_octet[elements[j]] or e[j] < el_n_deficient[elements[j]] ):

                            # Check that ring constraints don't disqualify bond-formation ( not a ring atom OR no existing double/triple bonds )
                            if j not in ring_atoms or sum([ _ for count,_ in enumerate(bond_mat[j]) if count != j and _ > 1 ]) == 0:                  
                                yield [(1,i,j),(1,j,i),(-1,i,i),(-1,j,j)]

                        # Check if CT from j can be performed to an electron deficient atom or one that can expand its octet. 
                        # This moved used to be performed as an else to the previous statement, but would miss some ylides. Now it is run in all cases to be safer.                                          
                        if bond_mat[j,j] > 1:
                            for k in reactive:
                                if k != i and k != j and ( el_expand_octet[elements[k]] or e[k] < el_n_deficient[elements[k]] ):

                                    # Check that ring constraints don't disqualify bond-formation ( not a ring atom OR no existing double/triple bonds )
                                    if j not in ring_atoms or sum([ _ for count,_ in enumerate(bond_mat[j]) if count != j and _ > 1 ]) == 0:                  
                                        yield [(1,i,j),(1,j,i),(-1,i,i),(-2,j,j),(1,k,k)]
                                                    
            # Move 5: i has a lone pair and a neighbor capable of forming a double bond, then a new pi-bond is formed with the neighbor from the lone pair
            if bond_mat[i,i] >= 2:
                for j in return_connections(i,bond_mat,inds=reactive):
                    # Check ring conditions on j
                    if j not in bridgeheads and ( j not in ring_atoms or sum([ _ for count,_ in enumerate(bond_mat[j]) if count != j and _ > 1 ]) == 0 ):
                        # Check octet conditions on j
                        if el_expand_octet[elements[j]] or e[j]+2 <= el_n_deficient[elements[j]]:                    
                            yield [(1,i,j),(1,j,i),(-2,i,i)]
                            
        # Move 6: i has a pi bond with j and the electronegativity of i is >= j, or a favorable change in aromaticity occurs, then the pi-bond is turned into a lone pair on i
        for j in return_connections(i,bond_mat,inds=reactive,min_order=2):
            formal_charges = return_formals(bond_mat, elements)
            if el_en[elements[i]] > el_en[elements[j]] or delta_aromatic(bond_mat,rings,move=((-1,i,j),(-1,j,i),(2,i,i)),formal_charges=formal_charges) or e[j] > el_n_deficient[elements[i]]:
                yield [(-1,i,j),(-1,j,i),(2,i,i)]

        # Move 7: i is electron deficient, bonded to j with unbound electrons, and the electronegativity of i is >= j, then an electron is tranferred from j to i
                # Note: very similar to move 4 except that a double bond is not formed. This is sometimes needed when j cannot expand its octet (as required by bond formation) but i still needs a full octet.
        if e[i] < el_n_deficient[elements[i]]:
            for j in return_connections(i,bond_mat,inds=reactive):
                if bond_mat[j,j] > 0 and el_en[elements[i]] > el_en[elements[j]]:
                    yield [(-1,j,j),(1,i,i)]

        # Move 8: i has an expanded octet and unbound electrons, then charge transfer to an atom within three bonds (controlled by local option) that is electron deficient or can expand its octet is attempted.
        if e[i] > el_n_deficient[elements[i]] and bond_mat[i,i] > 0:
            for j in reactive:
                if j != i and seps[i,j] < 3 and ( el_expand_octet[elements[j]] or e[j] < el_n_deficient[elements[j]] ):
                    yield [(-1,i,i),(1,j,j)]

        # # Move 9: i has an expanded octet and a bond with a neighbor that can be converted into a lone pair on the neighbor
        # if e[i] > el_n_deficient[elements[i]]:
        #     for j in return_connections(i,bond_mat,inds=reactive):
        #         if bond_mat[i,j] > 0:
        #             yield [(-1,i,j),(-1,j,i),(2,j,j)]
                    
    # Move 9: shuffle aromatic and anti-aromatic bonds 
    for i in rings:
        formal_charges = return_formals(bond_mat, elements)
        if is_aromatic(bond_mat,i,formal_charges) and len(i) % 2 == 0: 

            # Find starting point
            loop_ind = None
            for count_j,j in enumerate(i):

                # Get the indices of the previous and next atoms in the ring
                if count_j == 0:
                    prev_atom = i[len(i)-1]
                    next_atom = i[count_j + 1]
                elif count_j == len(i)-1:
                    prev_atom = i[count_j - 1]
                    next_atom = i[0]
                else:
                    prev_atom = i[count_j - 1]
                    next_atom = i[count_j + 1]

                # second check is to avoid starting on an allene
                if bond_mat[j,prev_atom] > 1 and bond_mat[j,next_atom] == 1:
                    if count_j % 2 == 0:
                        loop_ind = i[count_j::2] + i[:count_j:2]
                    else:
                        loop_ind = i[count_j::2] + i[1:count_j:2] # for an odd starting index the first index needs to be skipped
                    break

            # If a valid starting point was found
            if loop_ind:
                    
                # Loop over the atoms in the (anti)aromatic ring
                move = []
                for j in loop_ind:

                    # Get the indices of the previous and next atoms in the ring
                    if i.index(j) == 0:
                        prev_atom = i[len(i)-1]
                        next_atom = i[1]
                    elif i.index(j) == len(i)-1:
                        prev_atom = i[i.index(j) - 1]
                        next_atom = i[0]
                    else:
                        prev_atom = i[i.index(j) - 1]
                        next_atom = i[i.index(j) + 1]

                    # bonds are created in the forward direction.
                    if bond_mat[j,prev_atom] > 1:
                        move += [(-1,j,prev_atom),(-1,prev_atom,j),(1,j,next_atom),(1,next_atom,j)]

                    # If there is no double-bond (between j and the next or previous) then the shuffle does not apply.
                    # Note: lone pair and electron deficient aromatic moves are handled via Moves 3 and 1 above, respectively. Pi shuffles are only handled here.
                    else:
                        move = []
                        break

                # If a shuffle was generated then yield the move
                if move:
                    #print("move9")
                    yield move

def delta_aromatic(bond_mat,rings,move,formal_charges):
    ''' 
    Helper function for valid moves that determines if a proposed move will results in a change in aromaticity

    Parameters
    ----------
    bond_mat : array
               The bond electron matrix that the bond/electron rearrangments are calculated for.  

    rings: list
           List of lists holding the atom indices in each ring. Used to determine (anti) aromaticity.      

    move: tuple
          (int, i, j) where int is the value to be added to the ij position of the bond-electron matrix. 

    Returns
    -------
    change: boolean
            True indicates that the move will result in an increase in aromaticity, False that it will not. 
    '''
    tmp = copy(bond_mat)
    for k in move: tmp[k[1],k[2]]+=k[0]
    for r in rings:
        if ( is_aromatic(tmp,r,formal_charges) - is_aromatic(bond_mat,r,formal_charges) > 0):
            return True
    return False
    
def valid_bonds(ind,bond_mat,elements,reactive,ring_atoms):
    '''
    This is a simple version of `valid_moves()` that only returns valid bond-formation moves with some 
    quality checks (e.g., octet violations and allenes in rings). This function is used to generate the initial guesses for the Lewis Structure.

    Parameters
    ----------
    ind: int

    bond_mat: array
              The bond electron matrix that the bond/electron rearrangments are calculated for.      
    elements: list
              list of elements indexed to the bond_mat.         

    reactive: list
              List of integers corresponding to the indices of bond_mat where atoms capable of undergoing bond-elctron rearrangments reside.  
          
    ring_atoms: list
                List of integers corresponding to the indices of bond_mat where the atoms reside in a ring. Used to avoid forming allenes and alkynes within rings.

    Returns
    -------
    move: list of tuples,

          Each tuple in the list is composed of (int, i, j) where int is the value to be added to the ij position of the bond-electron matrix.
    '''

    e = return_e(bond_mat) # current number of electrons associated with each atom
    
    # Check if a bond can be formed between neighbors ( electron available AND ( octet can be expanded OR octet is incomplete ))
    if bond_mat[ind,ind] > 0 and ( el_expand_octet[elements[ind]] or e[ind] < el_n_deficient[elements[ind]] ):
        # Check that ring constraints don't disqualify bond-formation ( not a ring atom OR no existing double/triple bonds )
        if ind not in ring_atoms or sum([ _ for count,_ in enumerate(bond_mat[ind]) if count != ind and _ > 1 ]) == 0:  
           # Check on connected atoms
           for i in return_connections(ind,bond_mat,inds=reactive):
               # Electron available AND ( octect can be expanded OR octet is incomplete )
               if bond_mat[i,i] > 0 and ( el_expand_octet[elements[i]] or e[i] < el_n_deficient[elements[i]] ):
                   # Check that ring constraints don't disqualify bond-formation ( not a ring atom OR no existing double/triple bonds )
                   if i not in ring_atoms or sum([ _ for count,_ in enumerate(bond_mat[i]) if count != i and _ > 1 ]) == 0:                  
                       return [(1,ind,i),(1,i,ind),(-1,ind,ind),(-1,i,i)]                                       

def zwitterion_penalty(bond_mat, elements):
    """
    Calculate penalty for zwitterionic pairs (cation-anion).

    For zwitterionic pairs that are not formed between directly bonded atoms, a large penalty is applied (scale factor = 1.0).
    For zwitterionic pairs that are formed between directly bonded atoms, a small penalty is applied (scale factor = 0.1).

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
    
    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix.
    
    Returns
    -------
    penalty : float
              The penalty score for non-bonded zwitterionic pairs.
    """
    # Get formal charges
    fc = return_formals(bond_mat, elements)
    
    # Find positive and negative charges
    fc_pos = list(np.where(fc == 1.0)[0])
    fc_neg = list(np.where(fc == -1.0)[0])
    
    # Track valid zwitterionic pairs (between bonded atoms)
    valid_pos = []
    valid_neg = []
    
    # Find zwitterionic pairs between bonded atoms
    for ind in fc_pos:
        # Get negatively charged neighbors
        connections = [cind for cind, _ in enumerate(bond_mat[ind]) if _ > 0 and ind != cind]
        nn = [i for i in connections if i in fc_neg]
        if len(nn) == 1:
            valid_pos.append(ind)
            valid_neg.append(nn[0])
    
    # Calculate penalty for remaining charges (non-bonded zwitterionic pairs)
    penalty = len(set(fc_pos+fc_neg)-set(valid_pos+valid_neg)) * 1.0 + len(set(valid_pos+valid_neg)) * 0.1
    
    return penalty
          
def ionic_penalty(bond_mat, elements):
    """
    Calculate a general penalty for ionic species, for a single-ionic species, a penalty is applied.
    For +1 and -1 charges, a small penalty of 0.1 is applied.
    For +2/+3 and -2/-3 charges, a large penalty of 10.0 is applied.
    
    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
    
    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix.
    
    Returns
    -------
    penalty : float
              The penalty score for non-bonded zwitterionic pairs.
    """
    # Get formal charges
    fc = return_formals(bond_mat, elements)
    
    # find single charged ions
    single_cation = list(np.where(fc == 1.0)[0])
    single_anion = list(np.where(fc == -1.0)[0])
    
    # if a cation is placed on oxygen, set a penalty of 10.0
    single_cation_penalty = 0.0
    for i in single_cation:
        if elements[i] == 'O':
            single_cation_penalty += 1.0
    
    # if an anion is placed on hydrogen, set a penalty of 10.0
    single_anion_penalty = 0.0
    for i in single_anion:
        if elements[i] == 'H':
            single_anion_penalty += 1.0
    
    multi_fc = list(np.where(np.abs(fc) > 1.0)[0])
    
    # Calculate penalty for multi-charged ions
    multi_penalty = len(multi_fc) * 1.0
    
    return multi_penalty + single_cation_penalty + single_anion_penalty

def bmat_score(bond_mat,elements,rings,cat_en,an_en,rad_env,e_def,e_exp,w_def=-2,w_exp=0.1,w_formal=0.1,w_aro=-24,w_rad=0.1,w_zwitter=1.0,w_ionic=5.0,factor=0.0,verbose=False):
    """
    Score function used to rank candidate Lewis Structures during and after the exploration. The `find_lewis()` algorithm uses a few 
    different sets of weights at the start vs later parts of the algortihm by defining different versions  via anonymous functions.

    bmat_score is the objective function that is minimized by the "best" lewis structures. The explanation of terms is as follows:
        1. Every electron deficiency (less than octet) is strongly penalized. electron deficiencies on more electronegative atoms are penalized more strongly.
        2. Expanded octets are penalized at 0.1 per violation by default     
        3. Formal charges are penalized based on their sign and the electronegativity of the atom they occur on
        4. (anti)aromaticity is incentivized (penalized) depending on the size of the ring.  

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix. 
               Expects a list of lower-case elemental symbols.
    
    rings: list, default=None
           List of lists holding the atom indices in each ring. If none, then the rings are calculated.

    cat_en: array 
            Holds the cation electronegativity for each atom to determine the penalty for formal charges.

    an_en: array
           Holds the anion electronegativity for each atom to determine the penalty for formal charges. 

    rad_env: array
             Holds the radical environment term for each atom to determine the relative stability of hosting a radical. 

    e_tet: array
           Holds the number of electrons each atom needs to avoid a deficiency penalty (e.g., 8 for most organics, 
           2 for hydrogen).
    
    w_def: float, default=-1
           The weight of the electron deficiency term in the objective function for scoring bond-electron matrices.

    w_exp: float, default=0.1
           The weight of the term for penalizing octet expansions in the objective function for scoring bond-electon matrices.

    w_formal: float, default=0.1
              The weight of the formal charge term in the objective function for scoring bond-electon matrices.

    w_aro: float, default=-24
           The weight of the aromatic term in the objective function for scoring bond-electron matrices.

    w_rad: float, default=0.1
           The weight of the radical term in the objective function for scoring bond-electron matrices.

    factor: float, default=0
            An optional value that can be added to the score. Useful for normalizing with respect to something (e.g., the ionization potential of the molecule).

    verbose: bool, default=False
             Controls whether the individual components of the score are printed to standard out during evaluation.

    Returns
    -------
    score: float
           The score for the supplied bond-electron matrix.
    """
    en = cat_en
    formal_charges = return_formals(bond_mat, elements)
    if verbose:
        print("deficiency: {}".format(w_def*sum([ _*en[count] for count,_ in enumerate(return_def(bond_mat,elements,e_def)) ])))
        print("expanded: {}".format(w_exp*sum(return_expanded(bond_mat,elements,e_exp))))
        print("formals: {}".format(w_formal*sum([ _ * en[count]*np.exp(0.05*(_-1)) for count,_ in enumerate(return_formals(bond_mat,elements)) ])))
        print("aromatic: {}".format(w_aro*sum([ is_aromatic(bond_mat,_,formal_charges)/len(_) for _ in rings ])))
        print("radicals: {}".format(w_rad*sum([ rad_env[_]*(bond_mat[_,_]%2) for _ in range(len(bond_mat)) ])))
        print("zwitter: {}".format(w_zwitter*zwitterion_penalty(bond_mat, elements)))
        print("ionic: {}".format(w_ionic*ionic_penalty(bond_mat, elements)))

    # objective function (lower is better): sum ( electron_deficiency * electronegativity_of_atom ) + sum ( expanded_octets ) + sum ( formal charge * electronegativity_of_atom ) + sum ( aromaticity of rings ) + factor
    return w_def*sum([ _*en[count] for count,_ in enumerate(return_def(bond_mat,elements,e_def)) ]) + \
          w_exp*sum(return_expanded(bond_mat,elements,e_exp)) + \
          w_formal*sum([ _ * en[count]*np.exp(0.05*(_-1)) for count,_ in enumerate(return_formals(bond_mat,elements)) ]) + \
          w_aro*sum([ is_aromatic(bond_mat,_,formal_charges)/len(_) for _ in rings ]) + \
          w_zwitter*zwitterion_penalty(bond_mat, elements) + \
          w_rad*sum([ rad_env[_]*(bond_mat[_,_]%2) for _ in range(len(bond_mat)) ]) + \
          w_ionic*ionic_penalty(bond_mat, elements) + factor

def is_aromatic(bond_mat,ring,formal_charges):
    """
    Returns 1,0,-1 for aromatic, non-aromatic, and anti-aromatic respectively

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    ring : list 
           The atom indices of the ring being checking for aromaticity within bond_mat.

    Returns
    -------
    aromaticity: int
                 A value indicating aromaticity. 1,0,-1 for aromatic, non-aromatic, and anti-aromatic respectively.
    """
    # Initialize counter for pi electrons
    total_pi = 0
    
    # Get the indices of the multi-charged ions
    multi_fc = list(np.where(np.abs(formal_charges) > 1.0)[0])

    # Loop over the atoms in the ring
    for count_i,i in enumerate(ring):

        # if there is a multi-charged ion, then the ring can't be aromatic
        if i in multi_fc:
            return 0

        # Get the indices of the previous and next atoms in the ring
        if count_i == 0:
            prev_atom = ring[len(ring)-1]
            next_atom = ring[count_i + 1]
        elif count_i == len(ring)-1:
            prev_atom = ring[count_i - 1]
            next_atom = ring[0]
        else:
            prev_atom = ring[count_i - 1]
            next_atom = ring[count_i + 1]

        # If there isn't a bond between the atoms then the ring can't be aromatic (this can happen if the bond is non-covalent)
        if bond_mat[prev_atom,i] == 0:
            return 0
            
        # Check that there are pi electrons ( pi electrons on atom OR ( higher-order bond with ring neighbors) OR empty pi orbital
        if bond_mat[i,i] > 0 or ( bond_mat[i,prev_atom] > 1 or bond_mat[i,next_atom] > 1 ) or sum(bond_mat[i]) < 4:

            # Double-bonds are only counted with the next atom to avoid double counting. 
            if bond_mat[i,prev_atom] >= 2:
                total_pi += 0
            elif bond_mat[i,next_atom] >= 2:
                total_pi += 2
            # Handles carbenes: if only two bonds and there are less than three electrons then the orbital cannot participate in the pi system
#            elif (sum(bond_mat[i])-bond_mat[i,i])==2 and bond_mat[i,i] <= 2:
#                total_pi += 0
            # Elif logic is used, because if one of the previous occurs then the unbound electrons cannot be in the plane of the pi system.
            elif bond_mat[i,i] == 1:
                total_pi += 1
            elif bond_mat[i,i] >= 2:
                total_pi += 2

        # If there are no pi electrons then it is not an aromatic system
        else:
            return 0

    # If there isn't an even number of pi electrons it isn't aromatic/antiaromatic
    if total_pi % 2 != 0:
        return 0
    # The number of pi electron pairs needs to be less than the size of the ring for it to be aromatic
    # If this is excluded then spurious aromaticity can be observed for species like N1NN1    
    elif total_pi/2 >= len(ring):
        return 0
    # If the number of pi electron pairs is even then it is antiaromatic ring.
    elif total_pi/2 % 2 == 0:
        return -1
    # Else, the number of pi electron pairs is odd and it is an aromatic ring.
    else:
        return 1
    
def return_e(bond_mat):
    """
    Returns the valence electrons possessed by each atom (half of each bond) 

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    Returns
    -------
    valencies: array
               Contains the valence electrons possessed by each atom. This array is indexed to the bond-electron matrix.
    """
    return np.sum(2*bond_mat,axis=1)-np.diag(bond_mat)
    
# returns the electron deficiencies of each atom (based on octet goal)
def return_def(bond_mat,elements,e_def):
    """
    Returns returns the electron deficiencies of each atom (based on octet goal supplied via `e_tet`).

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix. 
               Expects a list of lower-case elemental symbols.

    e_def: array
           Holds the number of electrons each atom needs to avoid a deficiency penalty (e.g., 8 for most organics, 
           2 for hydrogen).

    Returns
    -------
    deficiencies: array
                  Contains the electron deficiencies of each atom. This array is indexed to the bond-electron matrix.

    Notes
    -----            
    Atoms with expanded octets return 0 not a negative value.
    """        
    tmp = np.sum(2*bond_mat,axis=1)-np.diag(bond_mat)-e_def
    return np.where(tmp<0,tmp,0)
        
def return_expanded(bond_mat,elements,e_exp):
    """
    Returns returns the number of surplus electrons beyond the target for each atom (based on octet goal 
    supplied via `e_tet`).

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix. 
               Expects a list of lower-case elemental symbols.

    e_exp: array
           Holds the number of electrons each atom can have until incurring an expanded octect penalty (e.g., 8 for most organics, 
           2 for hydrogen).

    Returns
    -------
    surplus: array
             Contains the excess electrons for each atom. This array is indexed to the bond-electron matrix.

    Notes
    -----            
    Atoms with electron deficiencies return 0 not a negative value.
    """                
    tmp = np.sum(2*bond_mat,axis=1)-np.diag(bond_mat)-e_exp
    return np.where(tmp>0,tmp,0)

def return_formals(bond_mat,elements): 
    """
    Returns returns the formal charge on each atom.

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix. 
               Expects a list of lower-case elemental symbols.

    Returns
    -------
    formals: array
             Contains the formal charge for each atom. This array is indexed to the bond-electron matrix.

    """
    return  np.array([el_valence[_] for _ in elements ]) - np.sum(bond_mat,axis=1)

def return_n_e_accept(bond_mat,elements): 
    """
    Returns returns the number of electrons each atom can accept without violating orbital constraints or breaking sigma bonds.
    Atoms that can expand their octets are treated as permitting two additional electrons beyond their orbital constraint (e.g.,
    sulfur can accept up to 10 electrons). Atoms participating in a double bonds are assumed to be able to accept at least two
    electrons since the double-bond can in principle be converted into a lone pair on the neighboring atom. 

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    elements : list 
               Contains elemental information indexed to the supplied adjacency matrix. 
               Expects a list of lower-case elemental symbols.

    Returns
    -------
    na: array
        contains the number of electrons that each atom can accept.
    """
    tmp = copy(bond_mat) # don't modify the supplied bond_mat
    tmp[~np.eye(tmp.shape[0], dtype=bool)] -= (tmp > 1)[~np.eye(tmp.shape[0], dtype=bool)] # -1 from off-diagonal elements>1
    tmp = tmp + np.diag([ -2 if el_expand_octet[_] else 0 for _ in elements ]) # -2 from diagonal for atoms that can expand octets.
    e_tet = np.array([ el_n_deficient[_] for _ in elements ]) # atom-wise octet requirements for determining electron deficiencies
    tmp = np.sum(2*tmp,axis=1)-np.diag(tmp)-e_tet # electron deficiency calculation
    return np.where(tmp<0,-tmp,0)

def return_n_e_donate(bond_mat,elements): 
    """
    Returns returns the number of electrons each atom can donate without breaking sigma bonds. This total basically comes to the 
    sum of non-sigma-bonded electrons associated with each atom. Atoms participating in a double bonds are assumed to be able to
    donote at least two electrons since the double-bond can in principle be converted into a lone pair on the atom. 

    Parameters
    ----------
    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    elements : list 
            `   Contains elemental information indexed to the supplied adjacency matrix. 
               Expects a list of lower-case elemental symbols.

    Returns
    -------
    na: array
        contains the number of electrons that each atom can accept.
    """
    tmp = copy(bond_mat) # don't modify the supplied bond_mat
    tmp[~np.eye(tmp.shape[0], dtype=bool)] -= (tmp > 0)[~np.eye(tmp.shape[0], dtype=bool)] # -1 from off-diagonal elements>0
    return np.sum(2*tmp,axis=1)-np.diag(tmp) # number of electrons associated with the atom after removing sigma-bonds.
    
def return_connections(ind,bond_mat,inds=None,min_order=1):
    """
    Returns indices of atoms bonded to the atom at `ind` according to the bond-electron matrix. 

    Parameters
    ----------
    ind : int
          The index of the bond-electron matrix that the connections are being returned for. 

    bond_mat : array
               A numpy array containing bond-orders in off-diagonal positions and unbound electrons along the diagonal.
               This array is indexed to the elements list. 

    inds : list, default=None 
           Optional list of indices of atoms that the user wants to restrict the return to. Useful for avoiding the return
           some trivial atoms that aren't relevant to resolving the Lewis structure. 

    min_order : int, default=1
                Optional argument that sets the threshold for determining a connection. If the user wishes to only find
                doubly-bonded connections, then this would be set to 2 (default: 1).

    Returns
    -------
    connections: list
                 Contains the indices of the bonded atoms subject to the `inds` and `min_order` arguments.
    """        
    if inds:
        return [ _ for _ in inds if bond_mat[ind,_] >= min_order and _ != ind ]
    else:
        return [ count for count,_ in enumerate(bond_mat[ind]) if _ >= min_order and count != ind ]        

def return_bo_dict(y,score_thresh=0.0):
    """
    Returns a dictionary of dictionaries containing the set of bond orders observed across all bond-electron matrices
    available to the yarpecule. For example, if atoms 1 and 2 have a double bond in one resonance structure but a single
    bond in another, this dictionary will hold set({1,2}) in the bo_dict[1][2] and bo_dict[2][1] positions. 
    
    Parameters
    ----------
    y: yarpecule
               Contains the bond_mats and bond_mat_scores needed for evaluation as attributesset.

    score_thresh: float
                  Only bond_mats with a score below this threshold are used for determining bond orders. If none of the 
                  bond_mats satisfy this threshold, then only the lowest scoring bond-electron matrix is used. 

    Returns
    -------
    bo_dict : dictionary of dictionaries
              Contains the set of observable bond-orders across all bond-electron matrices between atoms i and j at 
              each element. The keys of the dictionary are the atom indices. For example, to query the bond-order of
              the bond between atoms 4 and 6 you can use bo_dict[4][6] or bo_dict[6][4]. By default, unbonded atoms
              have `None` as their bond-order. 
    """
    inds = [ count for count,_ in enumerate(y.bond_mat_scores) if _ <= score_thresh ]
    if len(inds) == 0: inds = [0] # handle the case where no matrices satisfy the threshold. 
    bonds = [ (count_i,count_j) for count_i,i in enumerate(y.bond_mats[0]) for count_j,j in enumerate(i) if ( count_j > count_i and j > 0 ) ]
    bo_dict = { i:{ j:None for j in range(len(y.bond_mats[0])) } for i in range(len(y.bond_mats[0])) }
    for i in bonds:
        bo_dict[i[0]][i[1]] = set([ int(y.bond_mats[_][i[0],i[1]]) for _ in inds ])
        bo_dict[i[1]][i[0]] = bo_dict[i[0]][i[1]]
        
    return bo_dict

def adjust_metals(bond_mats,adj_mat,elements):
    """
    Accepts a list of bond mats and will adjust the bonding about the transition metals following the covalent bond
    classification (CBC) scheme. The adjacency matrix is used to determine where potential bonds exists. In short, 
    if adjacency matrix indicates a potential bond between the metal and an electron-decicient atom with a radical,
    then a covalent bond  is formed using an electron from the metal, if the atom is electron deficient without a
    radical, then a bond is formed using two electrons from the metal, if the atom is not electron deficient (pi or 
    lone pair containing) then no bond is formed (e.g., if the atom has a full octet then the bond is considered 
    dative). 
    
    Parameters
    ----------
    bond_mats: list of arrays
               Contains the bond_matrices that are being adjusted for the metal centers. 

    adj_mat: array
             Contains the connectivity of the molecular graph. 

    elements: list
              Contains the element labels for the atoms in the graph. 

    Returns
    -------
    bond_mats: list of arrays
               Contains the bond-electron matrices that have been updated to account for the nature of the ligands
               about the metal center. 
    """

    # list of electron counts for determining electron deficiencies
    e_def = np.array([ el_n_deficient[_] for _ in elements ])
    m_inds = [ count for count,_ in enumerate(elements) if _ in el_metals ]
    for b in bond_mats:
        defs = return_def(b,elements,e_def)                                
        for m_ind in m_inds:
            for con in return_connections(m_ind,adj_mat):            

                # type M - metal metal are handled at the end
                if con in m_inds:
                    continue                
                # type L - dative bonds
                elif defs[con] == 0:
                    continue                    
                # type X - covalent bonds
                elif b[con,con] % 2 != 0:                    
                    b[con,con] += -1
                    b[m_ind,m_ind] += -1
                    b[con,m_ind] += 1
                    b[m_ind,con] += 1
                # type Z - covalent bond, empty p orbital, using two electrons from the metal
                else:
                    b[m_ind,m_ind] += -2
                    b[con,m_ind] += 1
                    b[m_ind,con] += 1

        # handle metal-metal bonds
        electrons = return_e(b)
        for m_ind in m_inds:
            for con in return_connections(m_ind,adj_mat,inds=m_inds):
                count = 0
                while electrons[m_ind] < 12 and electrons[con] < 12 and b[con,con] > 0:
                    b[m_ind,m_ind] += -1
                    b[con,con] += -1
                    b[m_ind,con] += 1
                    b[con,m_ind] += 1
                    electrons = return_e(b)                    
                    count += 1
                    if count == 4:
                        break
    return bond_mats


