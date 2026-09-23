"""伏せ字版: Public リポジトリには hidden test を含めていません。

件数と配点の合計だけを本物に合わせたスタブで、中身は全て skip します。
ハーネス (bench/cli.py の preflight) が scoring.json のキーとこのファイルの
関数名の一致を確認するためだけに存在します。公開版でエージェントループを
回すことはできますが、Capability は常に 0 点になります。
"""

import pytest

def test_withheld_c04_1() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_2() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_3() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_4() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_5() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_6() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_7() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_8() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")

def test_withheld_c04_9() -> None:
    pytest.skip("hidden test は Public リポジトリに含まれていません")
