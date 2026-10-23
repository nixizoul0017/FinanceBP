"""Parse explicitly mapped business dates without guessing numeric identifiers."""
from datetime import date, datetime
import re
import unicodedata


def parse_business_date(value, *, field='date', allow_month=False):
    """Keep the source's calendar date; validate any supplied time before dropping it."""
    try:
        if isinstance(value, datetime):
            return date(value.year, value.month, value.day)
        if isinstance(value, date):
            return date(value.year, value.month, value.day)
        text=unicodedata.normalize('NFKC',str(value)).strip()
        if allow_month and re.fullmatch(r'\d{4}[-/]\d{1,2}',text):
            year,month=re.split(r'[-/]',text)
            return date(int(year),int(month),1)
        if re.fullmatch(r'\d{8}',text):
            return date(int(text[:4]),int(text[4:6]),int(text[6:]))
        # Only year-first dates are accepted. Do not guess day/month order or epoch units.
        match=re.fullmatch(
            r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})'
            r'(?:[T\s]+(\d{1,2}):(\d{1,2})(?::(\d{1,2})(\.\d{1,6})?)?'
            r'\s*(Z|[+-]\d{2}:?\d{2})?)?',text)
        if not match:
            raise ValueError
        year,month,day,hour,minute,second,fraction,zone=match.groups()
        calendar_day=date(int(year),int(month),int(day))
        if hour is not None:
            normalized=(calendar_day.isoformat()+f'T{int(hour):02}:{int(minute):02}:{int(second or 0):02}'
                        +(fraction or '')+(zone or ''))
            # Invalid times must fail too: a date prefix alone is not sufficient.
            datetime.fromisoformat(normalized)
        return calendar_day
    except (ValueError,TypeError,OverflowError):
        raise ValueError('invalid_date:'+field) from None
