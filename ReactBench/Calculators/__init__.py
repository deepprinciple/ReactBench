"""
ReactBench Calculators Package
Provides MLFF calculators for both run_pygsm.py and pysisyphus interfaces
"""

# Import LeftNet calculator classes
from .leftnet import (
    LeftNetMLFF, get_leftnet_calculator
)

from .mace import (
    MACEMLFF, get_mace_calculator
)

# Factory functions for calculators
# LeftNet
def create_leftnet_calculator(device="cpu"):
    """Create LeftNet calculator for run_pygsm.py"""
    return get_leftnet_calculator(device=device, use_autograd=True)

def create_leftnet_mlff(device="cpu"):
    """Create LeftNet MLFF for pysisyphus"""
    return LeftNetMLFF(device=device, use_autograd=True)


# LeftNet with direct forces
def create_leftnet_calculator_d(device="cpu"):
    """Create LeftNet calculator for run_pygsm.py with direct forces"""
    return get_leftnet_calculator(device=device, use_autograd=False)

def create_leftnet_mlff_d(device="cpu"):
    """Create LeftNet MLFF for pysisyphus with direct forces"""
    return LeftNetMLFF(device=device, use_autograd=False)

# MACE-pretrained
def create_mace_pretrained_calculator(device="cpu"):
    """Create MACE calculator for run_pygsm.py"""
    return get_mace_calculator(device=device, ver='pretrain')

def create_mace_pretrained_mlff(device="cpu"):
    """Create MACE MLFF for pysisyphus"""
    return MACEMLFF(device=device, ver='pretrain')

# MACE-finetuned
def create_mace_finetuned_calculator(device="cpu"):
    """Create MACE calculator for run_pygsm.py"""
    return get_mace_calculator(device=device, ver='finetuned')

def create_mace_finetuned_mlff(device="cpu"):
    """Create MACE MLFF for pysisyphus"""
    return MACEMLFF(device=device, ver='finetuned')


# Unified mapping: calculator name -> factory functions
CALCULATOR_FACTORIES = {
    'leftnet': {
        'calculator': create_leftnet_calculator,
        'mlff': create_leftnet_mlff,
    },
    'leftnet-d': {
        'calculator': create_leftnet_calculator_d,
        'mlff': create_leftnet_mlff_d,
    },
    'mace-pretrain': {
        'calculator': create_mace_pretrained_calculator,
        'mlff': create_mace_pretrained_mlff,
    },
    'mace-finetuned': {
        'calculator': create_mace_finetuned_calculator,
        'mlff': create_mace_finetuned_mlff,
    },
}

# Available calculator names
AVAILABLE_CALCULATORS = list(CALCULATOR_FACTORIES.keys())

def get_calculator(calc_name, device="cpu"):
    """
    Get calculator instance by name (for run_pygsm.py)
    
    Parameters
    ----------
    calc_name : str
        Name of the calculator (e.g., 'leftnet', 'leftnet-d')
    device : str
        Device to run calculations on ('cpu' or 'cuda')
    
    Returns
    -------
    LeftNetCalculator instance
    """
    if calc_name not in CALCULATOR_FACTORIES:
        raise ValueError(f"Unknown calculator: {calc_name}. Available: {AVAILABLE_CALCULATORS}")
    
    return CALCULATOR_FACTORIES[calc_name]['calculator'](device=device)

def get_mlff(calc_name, device="cpu"):
    """
    Get MLFF instance by name (for pysisyphus)
    
    Parameters
    ----------
    calc_name : str
        Name of the calculator (e.g., 'leftnet', 'leftnet-d')
    device : str
        Device to run calculations on ('cpu' or 'cuda')
    
    Returns
    -------
    LeftNetMLFF instance
    """
    if calc_name not in CALCULATOR_FACTORIES:
        raise ValueError(f"Unknown MLFF: {calc_name}. Available: {AVAILABLE_CALCULATORS}")
    
    return CALCULATOR_FACTORIES[calc_name]['mlff'](device=device)

__all__ = [
    # Utilities
    'CALCULATOR_FACTORIES', 'AVAILABLE_CALCULATORS',
    'get_calculator', 'get_mlff'
] 