import abc
import math
import datetime
from itertools import chain
import pandas as pd
import numpy as np
import typing
import operator
import re
from dataclasses import dataclass

from . import column
from .errors import PanSchArgumentError, PanSchNoIndexError
from pandas_schema.validation_warning import ValidationWarning
from pandas_schema.index import AxisIndexer, IndexValue, IndexType, RowIndexer, DualAxisIndexer
from pandas.api.types import is_categorical_dtype, is_numeric_dtype


class BaseValidation(abc.ABC):
    """
    A validation is, broadly, just a function that maps a data frame to a list of errors
    """

    def __init__(self, message: str = None, ):
        """
        Creates a new IndexSeriesValidation
        :param index: An index with which to select the series
            Otherwise it's a label (ie, index=0) indicates the column with the label of 0
        """
        self.custom_message = message

    def validate(self, df: pd.DataFrame) -> typing.Collection[ValidationWarning]:
        """
        Validates a data frame
        :param df: Data frame to validate
        :return: All validation failures detected by this validation
        """
        failed = self.get_failed_index(df)

        # Slice out the failed items, then map each into a list of validation warnings at each respective index
        warnings = []
        for index, value in failed(df).iteritems():
            warnings.append(ValidationWarning(self, {
                'row': index,
                'value': value
            }))
        return warnings

    @abc.abstractmethod
    def get_failed_index(self, df: pd.DataFrame) -> DualAxisIndexer:
        """
        Returns an indexer object that fully specifies which sections of the DataFrame this validation believes are
        invalid (both row and column-wise)
        """

    def message(self, warning: ValidationWarning) -> str:
        prefix = self.prefix(warning)

        if self.custom_message:
            suffix = self.custom_message
        else:
            suffix = self.default_message(warning)

        return "{} {}".format(prefix, suffix)

    @property
    def readable_name(self, **kwargs):
        """
        A readable name for this validation, to be shown in validation warnings
        """
        return type(self).__name__

    def default_message(self, warnings: ValidationWarning) -> str:
        return 'failed the {}'.format(self.readable_name)

    @abc.abstractmethod
    def prefix(self, warning: ValidationWarning):
        """
        Return a string that can be used to prefix a message that relates to this index

        This method is safe to override
        """

    def __or__(self, other: 'BaseValidation'):
        if not isinstance(other, BaseValidation):
            raise PanSchArgumentError('The "|" operator can only be used between two'
                                      'Validations that subclass {}'.format(
                self.__class__))

        return CombinedValidation(self, other, operator='or')


class IndexValidation(BaseValidation):
    def __init__(
            self,
            index: DualAxisIndexer,
            *args,
            **kwargs
    ):
        """
        Creates a new IndexSeriesValidation
        :param index: An index with which to select the series
            Otherwise it's a label (ie, index=0) indicates the column with the label of 0
        """
        super().__init__(*args, **kwargs)
        self.index = index

    def apply_index(self, df: pd.DataFrame):
        """
        Select a series using the data stored in this validation
        """
        return self.index(df)

    def prefix(self, warning: ValidationWarning):
        """
        Return a string that can be used to prefix a message that relates to this index

        This method is safe to override
        """
        ret = []

        if self.index.col_index is not None:
            col_str = self.index.col_index.for_message()
            if col_str:
                ret.append(col_str)

        ret.append('Row {}'.format(warning.props['row']))

        ret.append('"{}"'.format(warning.props['value']))

        return ' '.join(ret)


class SeriesValidation(IndexValidation):
    def __init__(self, index, *args, negated: bool = False, **kwargs):
        super().__init__(
            *args,
            index=DualAxisIndexer(
                col_index=index,
                row_index=RowIndexer(index=slice(None), typ=IndexType.POSITION),
            ),
            **kwargs
        )
        self.negated = negated

    def get_failed_index(self, df) -> DualAxisIndexer:
        series = self.apply_index(df)

        selected = self.validate_series(series)

        # Normally, validate_series returns the indices of the cells that passed the validation, but here we want the
        # cells that failed it, so invert the series (unless this is a negated validation)
        if self.negated:
            row_index = selected
        else:
            row_index = ~selected

        # Combine the index and the result series into one set of indexes
        return DualAxisIndexer(
            row_index=row_index,
            col_index=self.index.col_index
        )

    @abc.abstractmethod
    def validate_series(self, series: pd.Series) -> pd.Series:
        """
        Given a series, return a bool Series that has values of True if the series
            passes the validation, otherwise False
        """
        pass

    def __invert__(self):
        self.negated = not self.negated
        return self


#
# class BooleanSeriesValidation(IndexValidation, WarningSeriesGenerator):
#     """
#     Validation is defined by the function :py:meth:~select_cells that returns a boolean series.
#         Each cell that has False has failed the validation.
#
#         Child classes need not create their own :py:class:~pandas_schema.core.BooleanSeriesValidation.Warning subclass,
#         because the data is in the same form for each cell. You need only define a :py:meth~default_message.
#     """
#
#     def __init__(self, *args, negated=False, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.negated = negated
#
#     @abc.abstractmethod
#     def select_cells(self, series: pd.Series) -> pd.Series:
#         """
#         A BooleanSeriesValidation must return a boolean series. Each cell that has False has failed the
#             validation
#         :param series: The series to validate
#         """
#         pass
#
#     def validate_series(self, series, flatten=True) -> typing.Union[
#         typing.Iterable[ValidationWarning],
#         pd.Series
#     ]:
#         """
#         Validates a single series selected from the DataFrame
#         """
#         selection = self.select_cells(series)
#
#         if self.negated:
#             # If self.negated (which is not the default), then we don't need to flip the booleans
#             failed = selection
#         else:
#             # In the normal case we do need to flip the booleans, since select_cells returns True for cells that pass
#             # the validation, and we want cells that failed it
#             failed = ~selection
#
#         # Slice out the failed items, then map each into a list of validation warnings at each respective index
#         warnings = series[failed].to_frame().apply(
#             lambda row: [ValidationWarning(self, {
#                 'row': row.name,
#                 'value': row[0]
#             })], axis='columns', result_type='reduce')
#         # warnings = warnings.iloc[:, 0]
#
#         # If flatten, return a list of ValidationWarning, otherwise return a series of lists of Validation Warnings
#         if flatten:
#             return self.flatten_warning_series(warnings)
#         else:
#             return warnings
#
#     def get_warning_series(self, df: pd.DataFrame) -> pd.Series:
#         """
#         Validates a series and returns a series of warnings.
#         """
#         series = self.select_series(df)
#         return self.validate_series(series, flatten=False)
#
#     def prefix(self, warning: ValidationWarning):
#         parent = super().prefix(warning)
#         # Only in this subclass do we know the contents of the warning props, since we defined them in the
#         # validate_series method. Thus, we can now add row index information
#
#         return parent + ', Row {row}: "{value}"'.format(**warning.props)
#
#     def __invert__(self) -> 'BooleanSeriesValidation':
#         """
#         If a BooleanSeriesValidation is negated, it has the opposite result
#         """
#         self.negated = not self.negated
#         return self


class CombinedValidation(BaseValidation):
    """
    Validates if one and/or the other validation is true for an element
    """

    def message(self, warning: ValidationWarning) -> str:
        pass

    def __init__(self, validation_a: BaseValidation,
                 validation_b: BaseValidation, operator: str):
        super().__init__()
        self.operator = operator
        self.left = validation_a
        self.right = validation_b

    def get_warning_series(self, df: pd.DataFrame) -> pd.Series:
        # Let both validations separately select and filter a column
        left_errors = self.left.validate(df)
        right_errors = self.right.validate(df)

        if self.operator == 'and':
            # If it's an "and" validation, left, right, or both failing means an error,
            # so we can simply concatenate the lists of errors
            combined = left_errors.combine(
                right_errors,
                func=operator.add,
                fill_value=[]
            )
        elif self.operator == 'or':
            # [error] and [] = []
            # [error_1] and [error_2] = [error_2]
            # [] and [] = []
            # Thus, we can use the and operator to implement "or" validations
            combined = left_errors.combine(
                right_errors,
                func=lambda l, r: l + r if l and r else [],
                fill_value=[]
            )
            # func=lambda a, b: [] if len(a) == 0 or len(b) == 0 else a + b)
        else:
            raise Exception('Operator must be "and" or "or"')

        return combined

    def default_message(self, warnings: ValidationWarning) -> str:
        return '({}) {} ({})'.format(self.v_a.message, self.operator, self.v_b.message)
