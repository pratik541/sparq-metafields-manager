import io

from app import read_uploaded_csv


def csv_file(text, encoding):
    f = io.BytesIO(text.encode(encoding))
    f.name = "upload.csv"
    return f


class TestReadUploadedCsv:
    def test_reads_plain_utf8(self):
        df = read_uploaded_csv(csv_file("Title,SKU\nRing,ABC-1\n", "utf-8"))
        assert df["Title"].tolist() == ["Ring"]

    def test_reads_utf8_with_bom(self):
        df = read_uploaded_csv(csv_file("Title,SKU\nRing,ABC-1\n", "utf-8-sig"))
        assert df["SKU"].tolist() == ["ABC-1"]

    def test_falls_back_to_cp1252_excels_default_csv_export(self):
        # Regression: this exact scenario crashed the hosted app with an
        # unhandled UnicodeDecodeError. U+2019 (a right single quote, the
        # kind Excel auto-inserts) is 0x92 under cp1252 but not valid as a
        # standalone UTF-8 continuation byte, so utf-8-sig must fail first
        # and the cp1252 fallback must be what actually succeeds.
        text = "Title,Description\nRing,’s a nice ring\n"
        df = read_uploaded_csv(csv_file(text, "cp1252"))
        assert df["Description"].tolist() == ["’s a nice ring"]

    def test_rereads_from_the_start_on_each_attempt(self):
        # A failed utf-8-sig attempt partially consumes the stream; without
        # seeking back to 0 before the cp1252 retry, pandas would parse
        # whatever bytes were left over instead of the full file.
        text = "Title,Description\nRing,café ’ ring\n"
        df = read_uploaded_csv(csv_file(text, "cp1252"))
        assert df["Title"].tolist() == ["Ring"]
        assert df["Description"].tolist() == ["café ’ ring"]
