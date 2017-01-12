"""
Copyright 2016 Stephen Boyd, Enzo Busseti, Steven Diamond, Blackrock Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import cvxpy as cvx
import pandas as pd
import numpy as np
import copy
from .expression import Expression

__all__ = ['HcostModel', 'TcostModel']


class BaseCost(Expression):
    gamma = 1.  # it is changed by gamma * BaseCost()

    def __mul__(self,other):
        """Read the gamma parameter as a multiplication."""
        newobj=copy.copy(self)
        newobj.gamma *= other
        return newobj

    def __rmul__(self,other):
        """Read the gamma parameter as a multiplication."""
        return self.__mul__(other)


class HcostModel(BaseCost):
    """A model for holding costs.

    Attributes:
      borrow_costs: A dataframe of borrow costs.
      dividends: A dataframe of dividends.
    """

    def __init__(self, borrow_costs, dividends=None, cash_key = 'cash'):
        self.borrow_costs = borrow_costs
        self.dividends = dividends
        self.cash_key = cash_key

    def weight_expr(self, t, w_plus, z, value):
        ## TODO make expression a vector not a scalar (like tcost)
        """Estimate holding costs.

        Args:
          t: time of estimate
          wplus: holdings
          tau: time to estimate (default=t)
        """
        try:
            w_plus = w_plus[w_plus.index != self.cash_key]
            w_plus = w_plus.values
        except AttributeError:
            w_plus = w_plus[:-1]  # TODO fix when cvxpy pandas ready
        self.expression = self.borrow_costs.loc[t].values.T*cvx.neg(w_plus)
        if self.dividends is not None:
            self.expression -= self.dividends.loc[t].values*w_plus

        return self.expression

    def value_expr(self, t, h_plus, u):
        # TODO this might not be a great idea
        expression = self.weight_expr(t, w_plus=h_plus, z=None, value=None)
        return expression.value

    def optimization_log(self,t):
        return self.expression.value

    def simulation_log(self,t):
        return self.expression.value


class TcostModel(BaseCost):
    """A model for transaction costs.

    Attributes:
      volume: A dataframe of volumes.
      sigma: A dataframe of daily volatities.
      spread: A dataframe of bid-ask spreads.
      nonlin_coeff: A dataframe of coefficients for the nonlinear cost.
      power: The nonlinear tcost power.
    """
    def __init__(self, volume, sigma, spread, nonlin_coeff, power=1.5, coeff=1, cash_key='cash'):
        self.coeff = coeff
        self.volume = volume[volume.columns.difference([cash_key])]
        self.sigma = sigma[sigma.columns.difference([cash_key])]
        self.spread = spread[spread.columns.difference([cash_key])]
        self.nonlin_coeff = nonlin_coeff
        self.power = power
        self.cash_key = cash_key

    def weight_expr(self, t, w_plus, z, value):
        """Estimate tcosts given trades.

        Args:
          t: time of estimate
          z: trades
          value: portfolio value

        Returns:
          An expression for the tcosts.
        """

        try:
            z = z[z.index != self.cash_key]
            z = z.values
        except AttributeError:
            z = z[:-1]  # TODO fix when cvxpy pandas ready

        z_abs = cvx.abs(z)
        tmp = self.nonlin_coeff.loc[t] * self.sigma.loc[t] * \
            (value / self.volume.loc[t])**(self.power - 1)
        self.expression = cvx.mul_elemwise(self.spread.loc[t].values, z_abs) + \
            cvx.mul_elemwise(tmp.values, (z_abs)**self.power)

        return self.coeff * cvx.sum_entries(self.expression)  # TODO factor out the coeff

    def value_expr(self, t, h_plus, u):
        # TODO figure out why calling weight_expr is buggy
        abs_u = np.abs(u[:-1])
        tcosts = self.spread.loc[t]*abs_u + self.nonlin_coeff.loc[t] * \
                 self.sigma.loc[t] * abs_u**1.5/np.sqrt(self.volume.loc[t])

        self.tmp_tcosts=tcosts

        return tcosts.sum()

    def optimization_log(self,t):
        return self.expression.value.A1

    def simulation_log(self,t):
        ## TODO find another way
        return self.tmp_tcosts

    def weight_expr_ahead(self, t, tau, w_plus, z, value):
        """Returns the estimate at time t of tcost at time tau.
        """
        return self.weight_expr(t, None, z, value)

    def est_period(self, t, tau_start, tau_end, w_plus, z, value):
        """Returns the estimate at time t of tcost over given period.
        """
        K = (tau_end - tau_start).days
        return self.weight_expr(t, None, z / K, value) * K
