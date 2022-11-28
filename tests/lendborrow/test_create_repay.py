import warnings
import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta
from ..conftest import approx


def test_create_loan(controller_factory, stablecoin, collateral_token, market_controller, market_amm, monetary_policy, accounts, price_oracle, admin):
    user = accounts[0]
    with boa.env.anchor():
        with boa.env.prank(user):
            initial_amount = 10**25 # 10,000,000 WETH
            collateral_token._mint_for_testing(user, initial_amount)
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000) # 1,000 WETH

            l_amount = 2 * 10**6 * 10**18 # 2,000,000 USD
            active_band_prev = market_amm.active_band()
            with boa.reverts():
                market_controller.create_loan(c_amount, l_amount, 5)

            l_amount = 5 * 10**5 * 10**18 # 500,000
            # MIN_TICKS is 5, MAX_TICKS is 50
            with boa.reverts('Need more ticks'):
                market_controller.create_loan(c_amount, l_amount, 4)
            with boa.reverts('Need less ticks'):
                market_controller.create_loan(c_amount, l_amount, 400)

            with boa.reverts("Debt too high"):
                market_controller.create_loan(c_amount // 100, l_amount, 5)
                # collateral is 1,000 / 100 = 10 WETH to loan 500,000 USD

            p_oracle_up = market_amm.p_oracle_up(0)
            p_oracle_down = market_amm.p_oracle_down(0)
            debt_n1 = market_controller.calculate_debt_n1(c_amount, l_amount, 5)

            # Phew, the loan finally was created
            market_controller.create_loan(c_amount, l_amount, 5)
            # 1000 WETH to loan 500,000 USD, price is 3000, so collateral value is 3,000,000
            # 500,000 / 1000 = 500
            # But cannot do it again
            with boa.reverts('Loan already created'):
                market_controller.create_loan(c_amount, 1, 5)

            assert stablecoin.balanceOf(user) == l_amount
            assert l_amount == stablecoin.totalSupply() - stablecoin.balanceOf(market_controller)
            assert collateral_token.balanceOf(user) == initial_amount - c_amount

            assert market_controller.total_debt() == l_amount
            assert market_controller.debt(user) == l_amount

            p_up, p_down = market_controller.user_prices(user)
            p_lim = l_amount / c_amount / (1 - market_controller.loan_discount()/1e18)
            band_up, band_down = market_amm.read_user_tick_numbers(user)
            active_band_after = market_amm.active_band()

            # p_up: 543.3808593758635
            # p_down: 516.7497905745059
            # p_lim: 526.3157894736843
            # A: 100
            # band_up: 170
            # band_down: 174
            # active_band_prev: 0
            # active_band_after: 0
            # p_oracle_up: 3000.0
            # p_oracle_down: 2970.0
            # debt_n1: 170
            # amm.get_x_down(user): 529,951.5779202336

            for i in range(175):
                warnings.warn(f"for {i}, p_up: {market_amm.p_oracle_up(i)/1e18}, p_down: {market_amm.p_oracle_down(i)/1e18} ")
                warnings.warn(f"for {i}, p_current_up: {market_amm.p_current_up(i)/1e18}, p_current_down: {market_amm.p_current_down(i)/1e18} ")
            warnings.warn(f"p_up: {p_up/1e18}, p_down: {p_down/1e18}, p_lim: {p_lim}, market_amm.A(): {market_amm.A()}")
            warnings.warn(f"band_up: {band_up}, band_down: {band_down}, active_band_prev: {active_band_prev}, active_band_after: {active_band_after}")
            warnings.warn(f"p_oracle_up: {p_oracle_up/1e18}, p_oracle_down: {p_oracle_down/1e18}")
            warnings.warn(f"debt_n1: {debt_n1}")
            warnings.warn(f"get_x_down: {market_amm.get_x_down(user)/1e18}")
            assert approx(p_lim, (p_down * p_up)**0.5 / 1e18, 2 / market_amm.A())

            h = market_controller.health(user) / 1e18 + 0.02
            assert h >= 0.05 and h <= 0.06

            h = market_controller.health(user, True) / 1e18 + 0.02
            assert approx(h, c_amount * 3000 / l_amount - 1, 0.02)

            for band in range(170, 175):
                warnings.warn(f"WETH amount in band {band}: {market_amm.bands_y(band)/1e18}")

            target_band = 170
            warnings.warn(f"prev x: {market_amm.bands_x(target_band)/1e18}, y: {market_amm.bands_y(target_band)/1e18}")
            warnings.warn(f"prev active band: {market_amm.active_band()}")

            in_amount = 100 * 10 ** 18 # 100 crvUSD
            updated_oracle_price = 540 * 10 ** 18
            [x, y] = [val / 1e18 for val in market_amm.ext_calc_swap_out(True, in_amount, updated_oracle_price)[:2]]
            warnings.warn(f"calc swap out: x: {x}, y: {y}, price: {x/y}")
            [x, y] = [val / 1e18 for val in market_amm.ext_calc_swap_out(True, in_amount, 535* 10 **18)[:2]]
            warnings.warn(f"calc swap out: x: {x}, y: {y}, price: {x/y}")

            # with boa.env.prank(admin):
            #     price_oracle.set_price(updated_oracle_price)
            # with boa.env.prank(user):
            #     market_amm.exchange(0, 1, in_amount, 0)
            # warnings.warn(f"after x: {market_amm.bands_x(target_band)/1e18}, y: {market_amm.bands_y(target_band)/1e18}")
            # warnings.warn(f"after active band: {market_amm.active_band()}")
            # [x1, y1] = [val / 1e18 for val in market_amm.ext_calc_swap_out(True, in_amount, updated_oracle_price)[:2]]
            # warnings.warn(f"calc swap out: x1: {x1}, y1: {y1}, price: {x1/y1}")


@given(
    collateral_amount=st.integers(min_value=10**9, max_value=10**20),
    n=st.integers(min_value=5, max_value=50),
)
@settings(deadline=timedelta(seconds=1000))
def test_max_borrowable(market_controller, accounts, collateral_amount, n):
    max_borrowable = market_controller.max_borrowable(collateral_amount, n)
    with boa.reverts('Debt too high'):
        market_controller.calculate_debt_n1(collateral_amount, int(max_borrowable * 1.001), n)
    market_controller.calculate_debt_n1(collateral_amount, max_borrowable, n)


@pytest.fixture(scope="module")
def existing_loan(collateral_token, market_controller, accounts):
    user = accounts[0]
    c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
    l_amount = 5 * 10**5 * 10**18
    n = 5

    with boa.env.prank(user):
        collateral_token._mint_for_testing(user, c_amount)
        market_controller.create_loan(c_amount, l_amount, n)


def test_repay_all(stablecoin, collateral_token, market_controller, existing_loan, accounts):
    user = accounts[0]
    with boa.env.anchor():
        with boa.env.prank(user):
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
            amm = market_controller.amm()
            stablecoin.approve(market_controller, 2**256-1)
            market_controller.repay(2**100, user)
            assert market_controller.debt(user) == 0
            assert stablecoin.balanceOf(user) == 0
            assert collateral_token.balanceOf(user) == c_amount
            assert stablecoin.balanceOf(amm) == 0
            assert collateral_token.balanceOf(amm) == 0
            assert market_controller.total_debt() == 0


def test_repay_half(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]

    with boa.env.anchor():
        with boa.env.prank(user):
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
            debt = market_controller.debt(user)
            to_repay = debt // 2

            n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)
            stablecoin.approve(market_controller, 2**256-1)
            market_controller.repay(to_repay, user)
            n_after_0, n_after_1 = market_amm.read_user_tick_numbers(user)

            assert n_before_1 - n_before_0 + 1 == 5
            assert n_after_1 - n_after_0 + 1 == 5
            assert n_after_0 > n_before_0

            assert market_controller.debt(user) == debt - to_repay
            assert stablecoin.balanceOf(user) == debt - to_repay
            assert collateral_token.balanceOf(user) == 0
            assert stablecoin.balanceOf(market_amm) == 0
            assert collateral_token.balanceOf(market_amm) == c_amount
            assert market_controller.total_debt() == debt - to_repay


def test_add_collateral(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]

    with boa.env.anchor():
        c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)
        debt = market_controller.debt(user)

        n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)
        with boa.env.prank(user):
            collateral_token._mint_for_testing(user, c_amount)
            market_controller.add_collateral(c_amount, user)
        n_after_0, n_after_1 = market_amm.read_user_tick_numbers(user)

        assert n_before_1 - n_before_0 + 1 == 5
        assert n_after_1 - n_after_0 + 1 == 5
        assert n_after_0 > n_before_0

        assert market_controller.debt(user) == debt
        assert stablecoin.balanceOf(user) == debt
        assert collateral_token.balanceOf(user) == 0
        assert stablecoin.balanceOf(market_amm) == 0
        assert collateral_token.balanceOf(market_amm) == 2 * c_amount
        assert market_controller.total_debt() == debt


def test_borrow_more(stablecoin, collateral_token, market_controller, existing_loan, market_amm, accounts):
    user = accounts[0]

    with boa.env.anchor():
        with boa.env.prank(user):
            debt = market_controller.debt(user)
            more_debt = debt // 10
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

            n_before_0, n_before_1 = market_amm.read_user_tick_numbers(user)
            market_controller.borrow_more(0, more_debt)
            n_after_0, n_after_1 = market_amm.read_user_tick_numbers(user)

            assert n_before_1 - n_before_0 + 1 == 5
            assert n_after_1 - n_after_0 + 1 == 5
            assert n_after_0 < n_before_0

            assert market_controller.debt(user) == debt + more_debt
            assert stablecoin.balanceOf(user) == debt + more_debt
            assert collateral_token.balanceOf(user) == 0
            assert stablecoin.balanceOf(market_amm) == 0
            assert collateral_token.balanceOf(market_amm) == c_amount
            assert market_controller.total_debt() == debt + more_debt
