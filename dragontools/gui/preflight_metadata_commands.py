"""Qt-independent translation of metadata results into explicit widget calls."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetadataWidgetCall:
    method: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    optional: bool = True


def _text(data, name, default=''):
    return str(data.get(name) or default)


def _library_warning(data, supports_online):
    online = data.get('__online_series_suggestion__')
    if online is not None and supports_online:
        return [MetadataWidgetCall('mark_library_path_warning', (_text(data,'__library_path_warning__'),)),
                MetadataWidgetCall('apply_online_metadata_suggestion', (online,), optional=False)]
    return [MetadataWidgetCall('apply_unusable_library_series_match', kwargs={
        'message':_text(data,'__library_path_warning__'), 'series_name':_text(data,'series_name'),
        'suggested_series_name':_text(data,'suggested_series_name'),
        'base':_text(data,'base'), 'base_type':_text(data,'base_type')})]


def metadata_widget_calls(suggestion, *, supports_online):
    if not isinstance(suggestion,dict):
        return [MetadataWidgetCall('apply_online_metadata_suggestion',(suggestion,),optional=False)]
    data = suggestion
    if '__error__' in data:
        return [MetadataWidgetCall('mark_metadata_lookup_failed',(_text(data,'__error__'),))]
    if '__existing_series_dir__' in data:
        return [MetadataWidgetCall('apply_existing_series_dir',tuple(_text(data,n,d) for n,d in (
            ('__existing_series_dir__',''),('base',''),('series_name',''),('base_type',''),('source','folder_search'),('notice',''))))]
    if '__existing_movie_dir__' in data:
        return [MetadataWidgetCall('apply_existing_movie_dir',tuple(_text(data,n,d) for n,d in (
            ('__existing_movie_dir__',''),('base',''),('movie_name',''),('source','database'),('notice',''))))]
    if '__movie_library_warning__' in data:
        return [MetadataWidgetCall('apply_unusable_movie_match',kwargs={
            'message':_text(data,'__movie_library_warning__'),'movie_name':_text(data,'movie_name')})]
    if '__library_path_warning__' in data:
        return _library_warning(data,supports_online)
    if '__series_dir_choices__' in data:
        return [MetadataWidgetCall('apply_existing_series_dir_choices',kwargs={
            'choices':list(data.get('__series_dir_choices__') or []),
            'series_name':_text(data,'series_name'),'suggested_series_name':_text(data,'suggested_series_name')})]
    if '__local_series_missing__' in data:
        return [MetadataWidgetCall('mark_existing_series_dir_not_found')]
    return [MetadataWidgetCall('apply_online_metadata_suggestion',(suggestion,),optional=False)]
