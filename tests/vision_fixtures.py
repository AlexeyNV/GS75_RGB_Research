"""Small synthetic board, never actual LED positions or optical validation."""
import cv2
import numpy as np
from software.vision.aruco_markers import marker_image


def board():
    image=np.full((700,1200,3),70,np.uint8)
    for marker_id,(x,y) in enumerate([(60,50),(1000,50),(1000,520),(60,520)]):
        marker=marker_image(marker_id,20)
        image[y:y+160,x:x+160]=cv2.cvtColor(marker,cv2.COLOR_GRAY2BGR)
    return image


def illuminate(image,points):
    image=image.copy()
    for x,y,color in points: cv2.circle(image,(x,y),12,color,-1,cv2.LINE_AA)
    return image
